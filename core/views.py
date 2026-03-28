from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import Buyer, Seller
from django.http import HttpResponse

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
                return redirect('/signin/')
        elif user_type == 'seller':
            if Seller.objects.filter(email=email).exists():
                messages.error(request, 'A seller account with this email already exists.')
            else:
                Seller.objects.create(name=name, email=email, phone=phone)
                messages.success(request, 'Account created! Please sign in.')
                return redirect('/signin/')
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
            return HttpResponse("SIGNIN WORKS!")
        else:
            messages.error(request, 'No account found with that email and account type.')

    return render(request, 'auth.html')


def signout(request):
    request.session.flush()
    return redirect('/signin/')

# def add_cart(request):
#     user_id = request.session["user_id"]
#     buyer = Buyer.objects.get(id = user_id)

#     if not buyer:
#         messages.error(request, "NO USER FOUND SOMETHING LIEK TAHT")
#         return redirect("/")
    
# def add_item(request):
#     seller_id = request.session["user_id"]

#     item_name = request.POST.get("item_name")
    