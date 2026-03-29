import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import *
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum

def home(request):
    context = {
        'is_authenticated': 'user_id' in request.session,
        'user_type': request.session.get('user_type', ''),
        'user_name': request.session.get('user_name', ''),
    }
    return render(request, 'home.html', context)

def products(request):
    return HttpResponse("IN PRODUCT PAGE!")

def inventory(request):
    user, user_type = _get_valid_session_user(request)
    if not user or user_type != 'seller':
        return redirect('home')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        image_url = request.POST.get('image_url', '').strip()
        sku = request.POST.get('sku', '').strip()
        price_raw = request.POST.get('price', '').strip()
        quantity_raw = request.POST.get('quantity', '').strip()
        warehouse_location = request.POST.get('warehouse_location', '').strip()

        if not all([name, description, sku, price_raw, quantity_raw, warehouse_location]):
            messages.error(request, 'Please fill all required item and inventory fields.')
        elif Product.objects.filter(sku=sku).exists():
            messages.error(request, 'SKU already exists. Please use a unique SKU.')
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
                        warehouse_location=warehouse_location,
                    )

                    messages.success(request, 'Item and inventory created successfully.')
                    return redirect('inventory')

    context = {
        'seller_name': user.name,
        'warehouse_locations': ['North Hub', 'South Hub', 'East Hub', 'West Hub'],
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


def items(request):
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
        total_quantity = sum(max(inventory.quantity, 0) for inventory in inventories)
        warehouse_locations = sorted(
            {
                inventory.warehouse_location
                for inventory in inventories
                if inventory.warehouse_location
            }
        )

        if total_quantity <= 0:
            stock_status = 'Out of stock'
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
                'name': product.name,
                'description': product.description,
                'image_url': product.image_url,
                'sku': product.sku,
                'price': product.price,
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
        'user_name': user.name,
        'user_type': user_type,
        'item_rows': item_rows,
        'stats': {
            'total_items': len(item_rows),
            'total_stock_units': total_stock_units,
            'low_stock_items': low_stock_items,
            'out_of_stock_items': out_of_stock_items,
        },
    }
    return render(request, 'items.html', context)


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
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        user_type = request.POST.get('user_type', '')

        if not all([name, email, phone]):
            messages.error(request, 'All fields are required.')

        elif user_type == 'buyer':
            buyers = Buyer.objects.filter(email=email)
            if buyers.count() > 0:
                buyers = buyers.first()
                request.session['user_id'] = buyers.id
                request.session['user_type'] = user_type
                request.session['user_name'] = buyers.name
            else:
                Buyer.objects.create(name=name, email=email, phone=phone)
                messages.success(request, 'Account created! Please sign in.')
                return redirect('signin_page')
        elif user_type == 'seller':
            if Seller.objects.filter(email=email).exists():
                messages.error(request, 'A seller account with this email already exists.')
            else:
                Seller.objects.create(name=name, email=email, phone=phone)
                messages.success(request, 'Account created! Please sign in.')
                return redirect('signin_page')
        else:
            messages.error(request, 'Please select buyer or seller.')

    return render(request, 'auth.html')


def signin_page(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        user_type = request.POST.get('user_type', '')

        if user_type == 'buyer':
            user = Buyer.objects.filter(email=email).first()
        elif user_type == 'seller':
            user = Seller.objects.filter(email=email).first()
        else:
            user = None

        if user:
            request.session['user_id']   = user.id
            request.session['user_type'] = user_type
            request.session['user_name'] = user.name
            messages.success(request, f'Welcome back, {user.name}!')
            return redirect('home')
        else:
            messages.error(request, 'No account found with that email and account type.')

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

    return render(request, 'add_address.html')

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

def profile(request):
    if 'user_id' not in request.session or request.session.get('user_type') != 'buyer':
        messages.error(request, 'Please sign in as a buyer to view your profile.')
        return redirect('signin_page')

    buyer = Buyer.objects.get(id=request.session['user_id'])
    orders = (
        Order.objects
        .filter(buyer=buyer)
        .prefetch_related('items__product')
        .select_related('address')
        .order_by('-placed_at')
    )
    addresses   = Address.objects.filter(buyer=buyer)
    total_spent = orders.aggregate(total=Sum('total_amount'))['total'] or 0

    return render(request, 'profile.html', {
        'orders':      orders,
        'addresses':   addresses,
        'total_spent': total_spent,
        'user_name':   buyer.name,
        'user_email':  buyer.email,
        'user_type':   'buyer',
    })


def delete_order(request, order_id):
    if 'user_id' not in request.session or request.session.get('user_type') != 'buyer':
        return redirect('signin_page')

    if request.method == 'POST':
        buyer = Buyer.objects.get(id=request.session['user_id'])
        order = Order.objects.filter(id=order_id, buyer=buyer).first()
        if order:
            order.delete()
            messages.success(request, f'Order #{order_id} removed from your history.')
        else:
            messages.error(request, 'Order not found.')
    return redirect('profile')


def delete_address(request, address_id):
    if 'user_id' not in request.session:
        return redirect('signin_page')

    if request.method == 'POST':
        buyer = Buyer.objects.get(id=request.session['user_id'])
        address = Address.objects.filter(id=address_id, buyer=buyer).first()
        if address:
            address.delete()
            messages.success(request, 'Address deleted.')
        else:
            messages.error(request, 'Address not found.')
    return redirect('profile')


def set_default_address(request, address_id):
    if 'user_id' not in request.session:
        return redirect('signin_page')

    if request.method == 'POST':
        buyer = Buyer.objects.get(id=request.session['user_id'])
        Address.objects.filter(buyer=buyer).update(is_default=False)
        address = Address.objects.filter(id=address_id, buyer=buyer).first()
        if address:
            address.is_default = True
            address.save()
            messages.success(request, 'Default address updated.')
    return redirect('profile')


def update_profile(request):
    if 'user_id' not in request.session or request.session.get('user_type') != 'buyer':
        return redirect('signin_page')

    if request.method == 'POST':
        buyer = Buyer.objects.get(id=request.session['user_id'])
        name  = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        if name:
            buyer.name = name
            request.session['user_name'] = name   # keep session in sync
        if email:
            buyer.email = email
        buyer.save()
        messages.success(request, 'Profile updated.')
    return redirect('profile')


def change_password(request):
    if 'user_id' not in request.session or request.session.get('user_type') != 'buyer':
        return redirect('signin_page')

    if request.method == 'POST':
        buyer        = Buyer.objects.get(id=request.session['user_id'])
        old_password = request.POST.get('old_password', '')
        new_password = request.POST.get('new_password', '')

        if not check_password(old_password, buyer.password):
            messages.error(request, 'Current password is incorrect.')
            return redirect('profile')
        if len(new_password) < 8:
            messages.error(request, 'New password must be at least 8 characters.')
            return redirect('profile')

        buyer.password = make_password(new_password)
        buyer.save()
        messages.success(request, 'Password changed successfully.')
    return redirect('profile')


def delete_account(request):
    if 'user_id' not in request.session or request.session.get('user_type') != 'buyer':
        return redirect('signin_page')

    if request.method == 'POST':
        buyer = Buyer.objects.get(id=request.session['user_id'])
        buyer.delete()
        request.session.flush()
        messages.success(request, 'Your account has been deleted.')
        return redirect('home')
    return redirect('profile')