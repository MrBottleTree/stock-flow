from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import Buyer, Seller, Address, Order
from django.http import HttpResponse
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
