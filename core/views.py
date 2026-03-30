from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import Buyer, Seller, Address, Order, OrderItem, Cart, Inventory
from django.http import HttpResponse
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
    return HttpResponse("IN PRODUCT PAGE!")

def inventory(request):
    return HttpResponse("IN INVENTORY PAGE!")


def signup(request):
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
                return redirect('signin')
        elif user_type == 'seller':
            if Seller.objects.filter(email=email).exists():
                messages.error(request, 'A seller account with this email already exists.')
            else:
                Seller.objects.create(name=name, email=email, phone=phone)
                messages.success(request, 'Account created! Please sign in.')
                return redirect('signin')
        else:
            messages.error(request, 'Please select buyer or seller.')

    return render(request, 'auth.html')


def signin(request):
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


def signout(request):
    request.session.flush()
    return redirect('signin')


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


def cart(request):
    """Show the buyer's cart with an address selector."""
    if not request.session.get('user_id') or request.session.get('user_type') != 'buyer':
        messages.error(request, 'You must be signed in as a buyer to view your cart.')
        return redirect('signin')

    buyer = Buyer.objects.get(id=request.session['user_id'])

    try:
        buyer_cart = (
            Cart.objects
            .prefetch_related('cart_items__product__inventory')
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
            stock = item.product.inventory.quantity
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
