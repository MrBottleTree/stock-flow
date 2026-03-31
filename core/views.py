import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import *
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum, F
from django.db import transaction

def home(request):
    context = {
        'is_authenticated': 'user_id' in request.session,
        'user_type': request.session.get('user_type', ''),
        'user_name': request.session.get('user_name', ''),
    }
    return render(request, 'home.html', context)

def products(request):
    return redirect('items')

def inventory(request, product_id=None):
    user, user_type = _get_valid_session_user(request)
    if not user or user_type != 'seller':
        return redirect('home')

    product = None
    existing_inventory = None
    if product_id:
        product = Product.objects.filter(id=product_id, seller=user).first()
        if not product:
            messages.error(request, 'Product not found or you do not have permission to edit it.')
            return redirect('inventory')
        existing_inventory = Inventory.objects.filter(product=product).first()

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        image_url = request.POST.get('image_url', '').strip()
        sku = request.POST.get('sku', '').strip()
        price_raw = request.POST.get('price', '').strip()
        quantity_raw = request.POST.get('quantity', '').strip()
        warehouse_location_id = request.POST.get('warehouse_location', '').strip()

        if not all([name, description, sku, price_raw, quantity_raw, warehouse_location_id]):
            messages.error(request, 'Please fill all required item and inventory fields.')
        elif not product and Product.objects.filter(sku=sku).exists():
            messages.error(request, 'SKU already exists. Please use a unique SKU.')
        elif product and Product.objects.filter(sku=sku).exclude(id=product.id).exists():
            messages.error(request, 'SKU already exists on another product. Please use a unique SKU.')
        else:
            try:
                price = Decimal(price_raw)
                quantity = int(quantity_raw)
            except (InvalidOperation, ValueError):
                messages.error(request, 'Price must be a decimal number and quantity must be an integer.')
            else:
                if price <= 0 or quantity < 0:
                    messages.error(request, 'Price must be greater than 0 and quantity cannot be negative.')
                else:
                    # Look up the warehouse address by ID
                    try:
                        warehouse_address = Address.objects.get(
                            id=int(warehouse_location_id), seller=user
                        )
                    except (Address.DoesNotExist, ValueError):
                        messages.error(request, 'Invalid warehouse location selected.')
                        warehouse_address = None

                    if warehouse_address:
                        if product:
                            # Update existing product
                            product.name = name
                            product.description = description
                            product.image_url = image_url or None
                            product.sku = sku
                            product.price = price
                            product.save()

                            if existing_inventory:
                                existing_inventory.quantity = quantity
                                existing_inventory.warehouse_location = warehouse_address
                                existing_inventory.save()
                            else:
                                Inventory.objects.create(
                                    product=product,
                                    quantity=quantity,
                                    warehouse_location=warehouse_address,
                                )
                            messages.success(request, 'Item and inventory updated successfully.')
                        else:
                            # Create new product
                            product = Product.objects.create(
                                seller=user,
                                name=name,
                                description=description,
                                image_url=image_url or None,
                                sku=sku,
                                price=price,
                            )

                            Inventory.objects.create(
                                product=product,
                                quantity=quantity,
                                warehouse_location=warehouse_address,
                            )
                            messages.success(request, 'Item and inventory created successfully.')

                        return redirect('inventory')

    # Fetch seller's addresses to use as warehouse locations
    seller_addresses = Address.objects.filter(seller=user)
    context = {
        'seller_name': user.name,
        'user_type': user_type,
        'warehouse_locations': seller_addresses,
        'product': product,
        'inventory_data': {
            'quantity': existing_inventory.quantity if existing_inventory else '',
            'warehouse_location_id': existing_inventory.warehouse_location_id if existing_inventory and existing_inventory.warehouse_location else '',
        },
    }
    return render(request, 'inventory.html', context)


def _get_user_model(user_type):
    if user_type == 'buyer':
        return Buyer
    if user_type == 'seller':
        return Seller
    return None


def _serialize_user(user, user_type):
    return {
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'phone': user.phone,
        'user_type': user_type,
    }


def _parse_json_body(request):
    try:
        raw_body = request.body.decode('utf-8') if request.body else '{}'
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, JsonResponse({'success': False, 'message': 'Invalid JSON body.'}, status=400)

    if not isinstance(payload, dict):
        return None, JsonResponse({'success': False, 'message': 'JSON body must be an object.'}, status=400)

    return payload, None


def _method_not_allowed():
    return JsonResponse({'success': False, 'message': 'Method not allowed.'}, status=405)


def _get_valid_session_user(request):
    user_id = request.session.get('user_id')
    user_type = request.session.get('user_type', '')
    if not user_id:
        return None, None

    user_model = _get_user_model(user_type)
    if not user_model:
        return None, None

    user = user_model.objects.filter(id=user_id).first()
    if not user:
        return None, None

    return user, user_type


def _render_items_page(request, filter_sold_out=False):
    user, user_type = _get_valid_session_user(request)
    if not user:
        return redirect('home')

    products = list(
        Product.objects.select_related('seller').prefetch_related('inventories').all().order_by('-id')
    )

    item_rows = []
    total_stock_units = 0
    low_stock_items = 0
    out_of_stock_items = 0

    for product in products:
        inventories = list(product.inventories.all())
        
        # Skip products with no attached inventory
        if not inventories:
            continue
            
        total_quantity = sum(max(inventory.quantity, 0) for inventory in inventories)
        
        # Filter logic:
        # If on 'Sold Out' tab, skip items with stock > 0
        if filter_sold_out and total_quantity > 0:
            continue
        # If on 'All Items' tab, skip items with stock <= 0
        elif not filter_sold_out and total_quantity <= 0:
            continue

        warehouse_locations = sorted(
            {
                str(inventory.warehouse_location)
                for inventory in inventories
                if inventory.warehouse_location
            }
        )

        if total_quantity <= 0:
            stock_status = 'Sold out'
            stock_status_class = 'out'
            out_of_stock_items += 1
        elif total_quantity <= 10:
            stock_status = 'Low stock'
            stock_status_class = 'low'
            low_stock_items += 1
        else:
            stock_status = 'In stock'
            stock_status_class = 'in'

        total_stock_units += total_quantity

        item_rows.append(
            {
                'id': product.id,
                'name': product.name,
                'description': product.description,
                'image_url': product.image_url,
                'sku': product.sku,
                'price': product.price,
                'seller_id': product.seller.id,
                'seller_name': product.seller.name,
                'seller_email': product.seller.email,
                'total_quantity': total_quantity,
                'warehouse_locations': warehouse_locations,
                'warehouse_count': len(warehouse_locations),
                'stock_status': stock_status,
                'stock_status_class': stock_status_class,
            }
        )

    context = {
        'user_id': user.id,
        'user_name': user.name,
        'user_type': user_type,
        'item_rows': item_rows,
        'stats': {
            'total_items': len(item_rows),
            'total_stock_units': total_stock_units,
            'low_stock_items': low_stock_items,
            'out_of_stock_items': out_of_stock_items,
        },
        'is_sold_out_tab': filter_sold_out,
        'page_title': 'Sold Out Items' if filter_sold_out else 'Marketplace Item List',
        'page_subtitle': f"Welcome {user.name} ({user_type}). Browse all products currently out of stock." if filter_sold_out else f"Welcome {user.name} ({user_type}). Browse item health, seller details, and warehouse coverage in one place.",
    }
    return render(request, 'items.html', context)


def items(request):
    return _render_items_page(request, filter_sold_out=False)


def sold_out_items(request):
    return _render_items_page(request, filter_sold_out=True)


@csrf_exempt
def signup(request):
    if request.method == 'GET':
        return redirect('signup_page')

    if request.method != 'POST':
        return _method_not_allowed()

    payload, error_response = _parse_json_body(request)
    if error_response:
        return error_response

    name = str(payload.get('name', '')).strip()
    email = str(payload.get('email', '')).strip().lower()
    phone = str(payload.get('phone', '')).strip()
    password = str(payload.get('password', '')).strip()
    user_type = str(payload.get('user_type', '')).strip().lower()

    if not all([name, email, phone, password, user_type]):
        return JsonResponse({'success': False, 'message': 'name, email, phone, password and user_type are required.'}, status=400)

    user_model = _get_user_model(user_type)
    if not user_model:
        return JsonResponse({'success': False, 'message': 'user_type must be either buyer or seller.'}, status=400)

    if user_model.objects.filter(email=email).exists():
        return JsonResponse({'success': False, 'message': 'An account with this email already exists.'}, status=409)

    user = user_model.objects.create(
        name=name,
        email=email,
        phone=phone,
        password=make_password(password),
    )

    request.session['user_id'] = user.id
    request.session['user_type'] = user_type
    request.session['user_name'] = user.name

    return JsonResponse(
        {
            'success': True,
            'message': 'Signup successful.',
            'user': _serialize_user(user, user_type),
        },
        status=201,
    )


@csrf_exempt
def signin(request):
    if request.method == 'GET':
        return redirect('signin_page')

    if request.method != 'POST':
        return _method_not_allowed()

    payload, error_response = _parse_json_body(request)
    if error_response:
        return error_response

    email = str(payload.get('email', '')).strip().lower()
    password = str(payload.get('password', '')).strip()
    user_type = str(payload.get('user_type', '')).strip().lower()

    if not all([email, password, user_type]):
        return JsonResponse({'success': False, 'message': 'email, password and user_type are required.'}, status=400)

    user_model = _get_user_model(user_type)
    if not user_model:
        return JsonResponse({'success': False, 'message': 'user_type must be either buyer or seller.'}, status=400)

    user = user_model.objects.filter(email=email).first()
    if not user or not check_password(password, user.password):
        return JsonResponse({'success': False, 'message': 'Invalid credentials.'}, status=401)

    request.session['user_id'] = user.id
    request.session['user_type'] = user_type
    request.session['user_name'] = user.name

    return JsonResponse(
        {
            'success': True,
            'message': 'Signin successful.',
            'user': _serialize_user(user, user_type),
        },
        status=200,
    )


@csrf_exempt
def signout(request):
    if request.method == 'GET':
        return redirect('signout_page')

    if request.method != 'POST':
        return _method_not_allowed()

    request.session.flush()
    return JsonResponse({'success': True, 'message': 'Signout successful.'}, status=200)


def signup_page(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '').strip()
        confirm = request.POST.get('confirm', '').strip()
        user_type = request.POST.get('user_type', '')

        if not all([name, email, phone, password]):
            messages.error(request, 'All fields are required.')
        elif password != confirm:
            messages.error(request, 'Passwords do not match.')
        elif user_type not in ('buyer', 'seller'):
            messages.error(request, 'Please select buyer or seller.')
        else:
            user_model = _get_user_model(user_type)
            if user_model.objects.filter(email=email).exists():
                messages.error(request, f'An account with this email already exists. Please sign in.')
            else:
                user_model.objects.create(
                    name=name,
                    email=email,
                    phone=phone,
                    password=make_password(password),
                )
                messages.success(request, 'Account created! Please sign in.')
                return redirect('signin_page')

    return render(request, 'auth.html')


def signin_page(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '').strip()
        user_type = request.POST.get('user_type', '')

        if not all([email, password, user_type]):
            messages.error(request, 'Email, password, and account type are required.')
        else:
            user_model = _get_user_model(user_type)
            if not user_model:
                messages.error(request, 'Please select buyer or seller.')
            else:
                user = user_model.objects.filter(email=email).first()
                if not user:
                    messages.error(request, 'No account found with that email and account type.')
                elif not user.password or not check_password(password, user.password):
                    messages.error(request, 'Invalid password.')
                else:
                    request.session['user_id'] = user.id
                    request.session['user_type'] = user_type
                    request.session['user_name'] = user.name
                    messages.success(request, f'Welcome back, {user.name}!')
                    return redirect('home')

    return render(request, 'auth.html')


def signout_page(request):
    request.session.flush()
    return redirect('signin_page')


def add_address(request):
    # Require login
    if 'user_id' not in request.session:
        messages.error(request, 'Please sign in first.')
        return redirect('signin')

    if request.method == 'POST':
        line1 = request.POST.get('line1', '').strip()
        line2 = request.POST.get('line2', '').strip()
        city = request.POST.get('city', '').strip()
        state = request.POST.get('state', '').strip()
        postal_code = request.POST.get('postal_code', '').strip()
        country = request.POST.get('country', '').strip()

        if not all([line1, city, state, postal_code, country]):
            messages.error(request, 'Please fill in all required fields.')
        else:
            user_type = request.session.get('user_type')
            user_id = request.session.get('user_id')

            address = Address(
                line1=line1,
                line2=line2 or None,
                city=city,
                state=state,
                postal_code=postal_code,
                country=country,
            )

            if user_type == 'buyer':
                address.buyer = Buyer.objects.get(id=user_id)
            elif user_type == 'seller':
                address.seller = Seller.objects.get(id=user_id)

            address.save()
            messages.success(request, 'Address added successfully!')
            return redirect('home')

    context = {
        'user_type': request.session.get('user_type', ''),
        'user_name': request.session.get('user_name', ''),
    }
    return render(request, 'add_address.html', context)

def order_history(request):
    # Only buyers can view order history
    if not request.session.get('user_id') or request.session.get('user_type') != 'buyer':
        messages.error(request, 'You must be signed in as a buyer to view your orders.')
        return redirect('signin')

    buyer = Buyer.objects.get(id=request.session['user_id'])
    orders = (
        Order.objects
        .filter(buyer=buyer)
        .prefetch_related('items__product')
        .select_related('address')
        .order_by('-placed_at')
    )
    

    total_spent = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    context = {
        'is_authenticated': True,
        'user_type': 'buyer',
        'user_name': request.session.get('user_name', ''),
        'buyer': buyer,
        'orders': orders,
        'total_spent': total_spent,
    }
    return render(request, 'order_history.html', context)


def cart(request):
    """Show the buyer's cart with an address selector."""
    if not request.session.get('user_id') or request.session.get('user_type') != 'buyer':
        messages.error(request, 'You must be signed in as a buyer to view your cart.')
        return redirect('signin')

    buyer = Buyer.objects.get(id=request.session['user_id'])

    try:
        buyer_cart = (
            Cart.objects
            .prefetch_related('cart_items__product__inventories')
            .get(buyer=buyer)
        )
        cart_items = buyer_cart.cart_items.all()
    except Cart.DoesNotExist:
        buyer_cart = None
        cart_items = []

    # Annotate each item with its line total for display
    annotated_items = []
    subtotal = 0
    for item in cart_items:
        line_total = item.product.price * item.quantity
        subtotal += line_total
        try:
            stock = sum(max(inv.quantity, 0) for inv in item.product.inventories.all())
        except Exception:
            stock = 0
        annotated_items.append({
            'product': item.product,
            'quantity': item.quantity,
            'line_total': line_total,
            'stock': stock,
            'insufficient': stock < item.quantity,
        })

    addresses = buyer.addresses.all()

    context = {
        'is_authenticated': True,
        'user_type': 'buyer',
        'user_name': request.session.get('user_name', ''),
        'buyer': buyer,
        'cart': buyer_cart,
        'cart_items': annotated_items,
        'addresses': addresses,
        'subtotal': subtotal,
    }
    return render(request, 'cart.html', context)


def checkout(request):
    """POST-only: place an order from the buyer's cart."""
    if request.method != 'POST':
        return redirect('cart')

    if not request.session.get('user_id') or request.session.get('user_type') != 'buyer':
        messages.error(request, 'You must be signed in as a buyer to checkout.')
        return redirect('signin')

    buyer = Buyer.objects.get(id=request.session['user_id'])

    # Validate address
    address_id = request.POST.get('address_id')
    try:
        address = Address.objects.get(id=address_id, buyer=buyer)
    except Address.DoesNotExist:
        messages.error(request, 'Please select a valid delivery address.')
        return redirect('cart')

    # Fetch cart
    try:
        buyer_cart = Cart.objects.prefetch_related('cart_items__product').get(buyer=buyer)
    except Cart.DoesNotExist:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart')

    cart_items = list(buyer_cart.cart_items.select_related('product').all())
    if not cart_items:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart')

    try:
        with transaction.atomic():
            # Lock the relevant inventory rows to prevent race conditions
            product_ids = [ci.product_id for ci in cart_items]
            inventory_qs = (
                Inventory.objects
                .select_for_update()
                .filter(product_id__in=product_ids)
            )
            inv_map = {inv.product_id: inv for inv in inventory_qs}

            # Validate stock for every item before touching anything
            for ci in cart_items:
                inv = inv_map.get(ci.product_id)
                if inv is None or inv.quantity < ci.quantity:
                    product_name = ci.product.name
                    available = inv.quantity if inv else 0
                    raise ValueError(
                        f"Insufficient stock for '{product_name}' "
                        f"(requested {ci.quantity}, available {available})."
                    )

            # Compute total
            total_amount = sum(ci.product.price * ci.quantity for ci in cart_items)

            # Create order
            order = Order.objects.create(
                buyer=buyer,
                address=address,
                total_amount=total_amount,
                status='placed',
            )

            # Create order items & decrement inventory atomically
            for ci in cart_items:
                line_total = ci.product.price * ci.quantity
                OrderItem.objects.create(
                    order=order,
                    product=ci.product,
                    quantity=ci.quantity,
                    unit_price=ci.product.price,
                    line_total=line_total,
                )
                # Atomic DB-level decrement — never read-modify-write in Python
                Inventory.objects.filter(product=ci.product).update(
                    quantity=F('quantity') - ci.quantity
                )

            # Clear the cart
            buyer_cart.cart_items.all().delete()

    except ValueError as e:
        messages.error(request, str(e))
        return redirect('cart')
    except Exception:
        messages.error(request, 'Something went wrong. Please try again.')
        return redirect('cart')

    messages.success(request, f'Order #{order.id} placed successfully!')
    return redirect('order_history')


def item_detail(request, product_id):
    product = Product.objects.select_related('seller').prefetch_related('inventories').filter(id=product_id).first()

    if not product:
        messages.error(request, 'Product not found.')
        return redirect('items')

    user, user_type = _get_valid_session_user(request)

    # Handle add-to-cart POST
    if request.method == 'POST' and request.POST.get('action') == 'add_to_cart':
        if not user or user_type != 'buyer':
            messages.error(request, 'You must be signed in as a buyer to add items to cart.')
            return redirect('item_detail', product_id=product.id)

        try:
            qty = int(request.POST.get('quantity', 1))
        except (ValueError, TypeError):
            qty = 1

        if qty < 1:
            messages.error(request, 'Quantity must be at least 1.')
            return redirect('item_detail', product_id=product.id)

        # Calculate available stock
        inventories = list(product.inventories.all())
        available_stock = sum(max(inv.quantity, 0) for inv in inventories)

        if available_stock <= 0:
            messages.error(request, 'This item is out of stock.')
            return redirect('item_detail', product_id=product.id)

        # Get or create the buyer's cart
        cart, created = Cart.objects.get_or_create(
            buyer=user,
            defaults={'status': 'active'}
        )

        # Check if product already in cart
        cart_product = CartProduct.objects.filter(cart=cart, product=product).first()

        if cart_product:
            new_qty = cart_product.quantity + qty
            if new_qty > available_stock:
                messages.error(
                    request,
                    f'Cannot add {qty} more. You already have {cart_product.quantity} in cart '
                    f'and only {available_stock} available.'
                )
                return redirect('item_detail', product_id=product.id)
            cart_product.quantity = new_qty
            cart_product.save()
            messages.success(request, f'Updated cart — now {new_qty} × {product.name}.')
        else:
            if qty > available_stock:
                messages.error(
                    request,
                    f'Cannot add {qty} units. Only {available_stock} available.'
                )
                return redirect('item_detail', product_id=product.id)
            CartProduct.objects.create(cart=cart, product=product, quantity=qty)
            messages.success(request, f'Added {qty} × {product.name} to your cart.')

        return redirect('item_detail', product_id=product.id)

    # GET: Build context
    inventories = list(product.inventories.all())
    total_quantity = sum(max(inv.quantity, 0) for inv in inventories)
    warehouse_locations = sorted({
        str(inv.warehouse_location) for inv in inventories if inv.warehouse_location
    })

    if total_quantity <= 0:
        stock_status = 'Out of stock'
        stock_status_class = 'out'
    elif total_quantity <= 10:
        stock_status = 'Low stock'
        stock_status_class = 'low'
    else:
        stock_status = 'In stock'
        stock_status_class = 'in'

    context = {
        'product': product,
        'inventories': inventories,
        'total_quantity': total_quantity,
        'warehouse_count': len(warehouse_locations),
        'warehouse_locations': warehouse_locations,
        'stock_status': stock_status,
        'stock_status_class': stock_status_class,
        'user_type': user_type or '',
        'user_name': user.name if user else '',
    }
    return render(request, 'item_detail.html', context)

