import json

from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import Buyer, Seller
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt


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

    context = {
        'user_name': user.name,
        'user_type': user_type,
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

# def add_cart(request):
#     user_id = request.session["user_id"]
#     buyer = Buyer.objects.get(id = user_id)

#     if not buyer:
#         messages.error(request, "NO USER FOUND SOMETHING LIEK TAHT")
#         return redirect("/")
    
# def add_item(request):
#     seller_id = request.session["user_id"]

#     item_name = request.POST.get("item_name")
    