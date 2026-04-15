import json
import random
import smtplib
from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.conf import settings
from core.models import *
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum, F, Q
from django.db import transaction

def home(request):
    context = {
        'is_authenticated': 'user_id' in request.session,
        'user_type': request.session.get('user_type', ''),
        'user_name': request.session.get('user_name', ''),
        'unread_notification_count': _get_unread_notification_count(request),
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
        category_id = request.POST.get('category', '').strip()
        new_category_name = request.POST.get('new_category', '').strip()

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

                    # Resolve category selection or create a new one on the fly.
                    category_obj = None
                    if new_category_name:
                        category_obj, _ = Category.objects.get_or_create(
                            name=new_category_name.strip().title()
                        )
                    elif category_id:
                        category_obj = Category.objects.filter(id=category_id).first()

                    if warehouse_address:
                        if product:
                            # Update existing product
                            product.name = name
                            product.description = description
                            product.image_url = image_url or None
                            product.sku = sku
                            product.price = price
                            product.category = category_obj
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
                            messages.success(request, 'Item, category, and inventory updated successfully.')
                        else:
                            # Create new product
                            product = Product.objects.create(
                                seller=user,
                                name=name,
                                description=description,
                                image_url=image_url or None,
                                sku=sku,
                                price=price,
                                category=category_obj,
                            )

                            Inventory.objects.create(
                                product=product,
                                quantity=quantity,
                                warehouse_location=warehouse_address,
                            )
                            messages.success(request, 'Item, category, and inventory created successfully.')

                        return redirect('inventory')

    # Fetch seller's addresses to use as warehouse locations
    seller_addresses = Address.objects.filter(seller=user)
    categories = Category.objects.all()
    context = {
        'seller_name': user.name,
        'user_type': user_type,
        'warehouse_locations': seller_addresses,
        'categories': categories,
        'product': product,
        'inventory_data': {
            'quantity': existing_inventory.quantity if existing_inventory else '',
            'warehouse_location_id': existing_inventory.warehouse_location_id if existing_inventory and existing_inventory.warehouse_location else '',
        },
        'unread_notification_count': _get_unread_notification_count(request),
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


def _get_or_create_wallet(user):
    """Return the user's wallet, creating one if needed."""
    if user.wallet:
        return user.wallet
    wallet = Wallet.objects.create()
    user.wallet = wallet
    user.save(update_fields=['wallet'])
    return wallet


def _generate_otp_code():
    return f"{random.randint(100000, 999999)}"


def _verify_email_exists(email):
    """Best-effort check before OTP send.

    This validates syntax and asks SMTP if recipient is accepted via RCPT.
    Not all providers disclose existence, so non-auth/network errors are treated
    as inconclusive (and we allow OTP send attempt to continue).
    """
    try:
        validate_email(email)
    except ValidationError:
        return False, 'Please enter a valid email address.'

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=12) as server:
            if settings.EMAIL_USE_TLS:
                server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.mail(settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER)
            code, _ = server.rcpt(email)
            server.rset()

        if code in (250, 251):
            return True, ''
        if code >= 500:
            return False, 'This email address appears invalid or unreachable.'
        return True, ''
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            'SMTP authentication failed. If you are using Gmail, use a Google App Password in EMAIL_HOST_PASSWORD.'
        ) from exc
    except Exception:
        # Inconclusive check (provider/network policy). Let OTP send attempt decide.
        return True, ''


def _send_otp_email(email, otp_code, purpose):
    purpose_label = 'account signup' if purpose == 'signup' else 'password reset'
    subject = f"StockFlow OTP for {purpose_label}"
    message = (
        f"Your StockFlow OTP is: {otp_code}\n\n"
        f"This OTP is valid for 10 minutes.\n"
        f"If you did not request this, please ignore this email."
    )
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            'SMTP authentication failed. If you are using Gmail, use a Google App Password in EMAIL_HOST_PASSWORD.'
        ) from exc


def _create_and_send_otp(email, user_type, purpose):
    # Invalidate older active OTPs for this email/type/purpose.
    EmailOTP.objects.filter(
        email=email,
        user_type=user_type,
        purpose=purpose,
        is_used=False,
    ).update(is_used=True)

    otp_code = _generate_otp_code()
    EmailOTP.objects.create(
        email=email,
        user_type=user_type,
        purpose=purpose,
        otp_hash=make_password(otp_code),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    _send_otp_email(email, otp_code, purpose)


def _verify_latest_otp(email, user_type, purpose, otp_code):
    record = EmailOTP.objects.filter(
        email=email,
        user_type=user_type,
        purpose=purpose,
        is_used=False,
    ).order_by('-created_at').first()

    if not record:
        return False, 'No OTP request found. Please request a new OTP.'

    if timezone.now() > record.expires_at:
        return False, 'OTP has expired. Please request a new OTP.'

    if not check_password(otp_code, record.otp_hash):
        return False, 'Invalid OTP. Please try again.'

    record.is_used = True
    record.save(update_fields=['is_used'])
    return True, ''


def _render_items_page(request, filter_sold_out=False):
    user, user_type = _get_valid_session_user(request)
    if not user:
        return redirect('home')

    search_query = request.GET.get('q', '').strip()
    product_query = Product.objects.select_related('seller', 'category').prefetch_related('inventories').all().order_by('-id')
    if search_query:
        product_query = product_query.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )

    products = list(product_query)

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
                'category_name': product.category.name if product.category else 'Uncategorized',
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
        'search_query': search_query,
        'page_title': 'Sold Out Items' if filter_sold_out else 'Marketplace Item List',
        'page_subtitle': f"Welcome {user.name} ({user_type}). Browse all products currently out of stock." if filter_sold_out else f"Welcome {user.name} ({user_type}). Browse item health, seller details, and warehouse coverage in one place.",
        'unread_notification_count': _get_unread_notification_count(request),
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

    if len(password) < 8:
        return JsonResponse({'success': False, 'message': 'New password must be at least 8 characters.'}, status=400)

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
    # Auto-create wallet for new user
    _get_or_create_wallet(user)

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
        elif len(password) < 8:
            messages.error(request, 'New password must be at least 8 characters.')
        elif password != confirm:
            messages.error(request, 'Passwords do not match.')
        elif user_type not in ('buyer', 'seller'):
            messages.error(request, 'Please select buyer or seller.')
        else:
            user_model = _get_user_model(user_type)
            if user_model.objects.filter(email=email).exists():
                messages.error(request, f'An account with this email already exists. Please sign in.')
            else:
                try:
                    email_ok, email_error = _verify_email_exists(email)
                    if not email_ok:
                        messages.error(request, email_error)
                        return redirect('signup_page')

                    _create_and_send_otp(email, user_type, 'signup')
                except Exception as exc:
                    messages.error(request, f'Unable to send OTP right now. {exc}')
                else:
                    request.session['pending_signup'] = {
                        'name': name,
                        'email': email,
                        'phone': phone,
                        'password_hash': make_password(password),
                        'user_type': user_type,
                    }
                    messages.success(request, 'OTP sent to your email. Please verify to complete signup.')
                    return redirect('verify_signup_page')

    return render(request, 'auth.html')


def verify_signup_page(request):
    pending = request.session.get('pending_signup')
    if not pending:
        messages.error(request, 'No pending signup found. Please sign up again.')
        return redirect('signup_page')

    if request.method == 'POST':
        action = request.POST.get('action', 'verify').strip()

        if action == 'resend':
            try:
                _create_and_send_otp(pending['email'], pending['user_type'], 'signup')
                messages.success(request, 'A new OTP has been sent to your email.')
            except Exception:
                messages.error(request, 'Unable to resend OTP right now. Please try again.')
            return redirect('verify_signup_page')

        otp = request.POST.get('otp', '').strip()
        if not otp:
            messages.error(request, 'Please enter the OTP sent to your email.')
            return redirect('verify_signup_page')

        valid, error_message = _verify_latest_otp(
            pending['email'],
            pending['user_type'],
            'signup',
            otp,
        )
        if not valid:
            messages.error(request, error_message)
            return redirect('verify_signup_page')

        user_model = _get_user_model(pending['user_type'])
        if user_model.objects.filter(email=pending['email']).exists():
            request.session.pop('pending_signup', None)
            messages.error(request, 'An account with this email already exists. Please sign in.')
            return redirect('signin_page')

        new_user = user_model.objects.create(
            name=pending['name'],
            email=pending['email'],
            phone=pending['phone'],
            password=pending['password_hash'],
        )
        _get_or_create_wallet(new_user)

        request.session.pop('pending_signup', None)
        messages.success(request, 'Email verified! Account created successfully. Please sign in.')
        return redirect('signin_page')

    return render(
        request,
        'verify_otp.html',
        {
            'flow_title': 'Verify Your Email',
            'flow_subtitle': 'Enter the OTP sent to your email to complete signup.',
            'email': pending.get('email', ''),
            'post_url_name': 'verify_signup_page',
        },
    )


def forgot_password_page(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        user_type = request.POST.get('user_type', '').strip().lower()

        if not email or user_type not in ('buyer', 'seller'):
            messages.error(request, 'Please provide a valid email and account type.')
            return redirect('forgot_password_page')

        user_model = _get_user_model(user_type)
        user = user_model.objects.filter(email=email).first() if user_model else None
        if not user:
            messages.error(request, 'No account found for that email and account type.')
            return redirect('forgot_password_page')

        try:
            email_ok, email_error = _verify_email_exists(email)
            if not email_ok:
                messages.error(request, email_error)
                return redirect('forgot_password_page')

            _create_and_send_otp(email, user_type, 'forgot_password')
        except Exception as exc:
            messages.error(request, f'Unable to send OTP right now. {exc}')
            return redirect('forgot_password_page')

        request.session['pending_password_reset'] = {
            'email': email,
            'user_type': user_type,
        }
        messages.success(request, 'OTP sent to your email. Enter it below to reset your password.')
        return redirect('reset_password_page')

    return render(request, 'forgot_password.html')


def reset_password_page(request):
    pending = request.session.get('pending_password_reset')
    if not pending:
        messages.error(request, 'No pending password reset found. Please request OTP first.')
        return redirect('forgot_password_page')

    if request.method == 'POST':
        action = request.POST.get('action', 'reset').strip()

        if action == 'resend':
            try:
                _create_and_send_otp(pending['email'], pending['user_type'], 'forgot_password')
                messages.success(request, 'A new OTP has been sent to your email.')
            except Exception:
                messages.error(request, 'Unable to resend OTP right now. Please try again.')
            return redirect('reset_password_page')

        otp = request.POST.get('otp', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not all([otp, new_password, confirm_password]):
            messages.error(request, 'OTP, new password, and confirm password are required.')
            return redirect('reset_password_page')

        if len(new_password) < 8:
            messages.error(request, 'New password must be at least 8 characters.')
            return redirect('reset_password_page')

        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('reset_password_page')

        valid, error_message = _verify_latest_otp(
            pending['email'],
            pending['user_type'],
            'forgot_password',
            otp,
        )
        if not valid:
            messages.error(request, error_message)
            return redirect('reset_password_page')

        user_model = _get_user_model(pending['user_type'])
        user = user_model.objects.filter(email=pending['email']).first() if user_model else None
        if not user:
            request.session.pop('pending_password_reset', None)
            messages.error(request, 'Account not found.')
            return redirect('forgot_password_page')

        user.password = make_password(new_password)
        user.save(update_fields=['password'])

        request.session.pop('pending_password_reset', None)
        messages.success(request, 'Password reset successful. Please sign in with your new password.')
        return redirect('signin_page')

    return render(
        request,
        'verify_otp.html',
        {
            'flow_title': 'Reset Password',
            'flow_subtitle': 'Enter OTP and choose a new password.',
            'email': pending.get('email', ''),
            'post_url_name': 'reset_password_page',
            'show_password_fields': True,
        },
    )


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
            # Redirect to the most useful page for each role
            if request.session.get('user_type') == 'seller':
                return redirect('inventory')
            return redirect('items')

    context = {
        'user_type': request.session.get('user_type', ''),
        'user_name': request.session.get('user_name', ''),
        'unread_notification_count': _get_unread_notification_count(request),
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
        'unread_notification_count': _get_unread_notification_count(request),
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
        'unread_notification_count': _get_unread_notification_count(request),
    }
    return render(request, 'cart.html', context)


def checkout(request):
    """POST-only: place an order from the buyer's cart.
    Orders start as 'Pending' — inventory is NOT deducted until all sellers approve.
    """
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
        buyer_cart = Cart.objects.prefetch_related('cart_items__product__seller').get(buyer=buyer)
    except Cart.DoesNotExist:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart')

    cart_items = list(buyer_cart.cart_items.select_related('product__seller').all())
    if not cart_items:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart')

    try:
        with transaction.atomic():
            # Validate stock availability (but do NOT deduct yet)
            product_ids = [ci.product_id for ci in cart_items]
            inventory_qs = (
                Inventory.objects
                .filter(product_id__in=product_ids)
            )
            # Build map: product_id → total stock across all warehouses
            inv_totals = {}
            for inv in inventory_qs:
                inv_totals[inv.product_id] = inv_totals.get(inv.product_id, 0) + max(inv.quantity, 0)

            for ci in cart_items:
                available = inv_totals.get(ci.product_id, 0)
                if available < ci.quantity:
                    product_name = ci.product.name
                    raise ValueError(
                        f"Insufficient stock for '{product_name}' "
                        f"(requested {ci.quantity}, available {available})."
                    )

            # Compute total
            total_amount = sum(ci.product.price * ci.quantity for ci in cart_items)

            # ── WALLET: Debit buyer ──
            buyer_wallet = _get_or_create_wallet(buyer)
            if buyer_wallet.balance < total_amount:
                raise ValueError(
                    f"Insufficient wallet balance. Your balance is ₹{buyer_wallet.balance} "
                    f"but the order total is ₹{total_amount}. Please add funds first."
                )
            buyer_wallet.balance -= total_amount
            buyer_wallet.save()

            # Create order with Pending status
            order = Order.objects.create(
                buyer=buyer,
                address=address,
                total_amount=total_amount,
                status='Pending',
            )

            # Record debit transaction
            Transaction.objects.create(
                wallet=buyer_wallet,
                order=order,
                transaction_type='debit',
                amount=total_amount,
                balance_after=buyer_wallet.balance,
                description=f"Payment for order #{order.id} (held in escrow until seller approval)",
            )

            # Create order items — all start as Pending
            order_items_by_seller = {}
            for ci in cart_items:
                line_total = ci.product.price * ci.quantity
                oi = OrderItem.objects.create(
                    order=order,
                    product=ci.product,
                    quantity=ci.quantity,
                    unit_price=ci.product.price,
                    line_total=line_total,
                    status='Pending',
                )
                seller = ci.product.seller
                if seller.id not in order_items_by_seller:
                    order_items_by_seller[seller.id] = {'seller': seller, 'items': []}
                order_items_by_seller[seller.id]['items'].append(oi)

            # ── Notification for the BUYER ──
            seller_names = ', '.join(
                data['seller'].name for data in order_items_by_seller.values()
            )
            Notification.objects.create(
                buyer=buyer,
                order=order,
                notification_type='order_placed',
                message=(
                    f"Your order #{order.id} has been placed and is awaiting approval "
                    f"from: {seller_names}. You will be notified once all sellers respond."
                ),
            )
            Notification.objects.create(
                buyer=buyer,
                order=order,
                notification_type='wallet_debited',
                message=(
                    f"₹{total_amount} has been debited from your wallet for order #{order.id}. "
                    f"This amount is held in escrow until all sellers respond."
                ),
            )

            # ── Notifications for each SELLER ──
            for seller_id, data in order_items_by_seller.items():
                seller = data['seller']
                product_list = ', '.join(
                    f"{oi.product.name} (×{oi.quantity})" for oi in data['items']
                )
                for oi in data['items']:
                    Notification.objects.create(
                        seller=seller,
                        order=order,
                        order_item=oi,
                        notification_type='approval_request',
                        message=(
                            f"Buyer {buyer.name} placed order #{order.id} "
                            f"including your product '{oi.product.name}' (×{oi.quantity}, "
                            f"₹{oi.line_total}). Please approve or reject this item."
                        ),
                    )

            # Clear the cart
            buyer_cart.cart_items.all().delete()

    except ValueError as e:
        messages.error(request, str(e))
        return redirect('cart')
    except Exception:
        messages.error(request, 'Something went wrong. Please try again.')
        return redirect('cart')

    messages.success(
        request,
        f'Order #{order.id} placed! ₹{total_amount} debited from your wallet (held in escrow).'
    )
    return redirect('order_history')


def cart_remove(request, product_id):
    """Remove a single product from the buyer's cart."""
    if not request.session.get('user_id') or request.session.get('user_type') != 'buyer':
        return redirect('signin_page')

    buyer = Buyer.objects.get(id=request.session['user_id'])
    cart_obj = Cart.objects.filter(buyer=buyer).first()
    if cart_obj:
        deleted, _ = CartProduct.objects.filter(
            cart=cart_obj, product_id=product_id
        ).delete()
        if deleted:
            messages.success(request, 'Item removed from cart.')
        else:
            messages.error(request, 'Item not found in cart.')
    return redirect('cart')


def cart_update(request, product_id):
    """Update the quantity of a product in the buyer's cart (POST only)."""
    if request.method != 'POST':
        return redirect('cart')

    if not request.session.get('user_id') or request.session.get('user_type') != 'buyer':
        return redirect('signin_page')

    buyer = Buyer.objects.get(id=request.session['user_id'])
    cart_obj = Cart.objects.filter(buyer=buyer).first()
    if not cart_obj:
        return redirect('cart')

    try:
        qty = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        messages.error(request, 'Invalid quantity.')
        return redirect('cart')

    if qty < 1:
        # Treat qty < 1 as a remove
        CartProduct.objects.filter(cart=cart_obj, product_id=product_id).delete()
        messages.success(request, 'Item removed from cart.')
        return redirect('cart')

    product = Product.objects.prefetch_related('inventories').filter(id=product_id).first()
    if not product:
        messages.error(request, 'Product not found.')
        return redirect('cart')

    available = sum(
        max(inv.quantity, 0) for inv in product.inventories.all()
    )
    if qty > available:
        messages.error(
            request,
            f'Only {available} unit{"s" if available != 1 else ""} of '
            f'"{product.name}" available.'
        )
        return redirect('cart')

    updated = CartProduct.objects.filter(
        cart=cart_obj, product_id=product_id
    ).update(quantity=qty)
    if updated:
        messages.success(request, f'Cart updated — {qty} × {product.name}.')
    else:
        messages.error(request, 'Item not found in cart.')
    return redirect('cart')


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
        'unread_notification_count': _get_unread_notification_count(request),
    }
    return render(request, 'item_detail.html', context)


def profile(request):
    user, user_type = _get_valid_session_user(request)
    if not user:
        messages.error(request, 'Please sign in to view your profile.')
        return redirect('signin_page')

    if user_type == 'buyer':
        orders = (
            Order.objects
            .filter(buyer=user)
            .prefetch_related('items__product')
            .select_related('address')
            .order_by('-placed_at')
        )
        addresses = Address.objects.filter(buyer=user)
        total_spent = orders.aggregate(total=Sum('total_amount'))['total'] or 0
        total_earned = 0
    else:  # seller
        orders = (
            Order.objects
            .filter(items__product__seller=user)
            .distinct()
            .prefetch_related('items__product')
            .select_related('address')
            .order_by('-placed_at')
        )
        addresses = Address.objects.filter(seller=user)
        total_spent = 0
        total_earned = OrderItem.objects.filter(product__seller=user, status='Approved').aggregate(total=Sum('line_total'))['total'] or 0

    return render(request, 'profile.html', {
        'orders':      orders,
        'addresses':   addresses,
        'total_spent': total_spent,
        'total_earned': total_earned,
        'user_name':   user.name,
        'user_email':  user.email,
        'user_type':   user_type,
        'unread_notification_count': _get_unread_notification_count(request),
    })


def delete_order(request, order_id):
    if 'user_id' not in request.session or request.session.get('user_type') != 'buyer':
        return redirect('signin_page')

    if request.method == 'POST':
        buyer = Buyer.objects.get(id=request.session['user_id'])
        order = Order.objects.filter(id=order_id, buyer=buyer).first()
        if not order:
            messages.error(request, 'Order not found.')
        elif order.status == 'Pending':
            messages.error(request, 'Cannot delete a pending order — wait for seller response, or it will be auto-resolved.')
        else:
            order.delete()
            messages.success(request, f'Order #{order_id} removed from your history.')
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

    user_type = request.session.get('user_type')
    user_id = request.session['user_id']

    if request.method == 'POST':
        if user_type == 'buyer':
            buyer = Buyer.objects.get(id=user_id)
            Address.objects.filter(buyer=buyer).update(is_default=False)
            addr = Address.objects.filter(id=address_id, buyer=buyer).first()
        elif user_type == 'seller':
            seller = Seller.objects.get(id=user_id)
            Address.objects.filter(seller=seller).update(is_default=False)
            addr = Address.objects.filter(id=address_id, seller=seller).first()
        else:
            addr = None

        if addr:
            addr.is_default = True
            addr.save()
            messages.success(request, 'Default address updated.')
            
    if user_type == 'seller':
        return redirect('inventory')
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


# ──────────────────────────────────────────────────────────────
# NOTIFICATION VIEWS
# ──────────────────────────────────────────────────────────────

def _get_unread_notification_count(request):
    """Return the unread notification count for the current session user."""
    user_id = request.session.get('user_id')
    user_type = request.session.get('user_type', '')
    if not user_id:
        return 0
    if user_type == 'buyer':
        return Notification.objects.filter(buyer_id=user_id, is_read=False).count()
    elif user_type == 'seller':
        return Notification.objects.filter(seller_id=user_id, is_read=False).count()
    return 0


def notifications(request):
    """Notifications page for both buyers and sellers."""
    user, user_type = _get_valid_session_user(request)
    if not user:
        messages.error(request, 'Please sign in to view notifications.')
        return redirect('signin_page')

    if user_type == 'buyer':
        notifs = Notification.objects.filter(buyer=user).select_related('order')
    else:
        notifs = Notification.objects.filter(seller=user).select_related('order', 'order_item', 'order_item__product')

    unread_count = notifs.filter(is_read=False).count()
    total_count = notifs.count()
    read_count = total_count - unread_count

    context = {
        'user_name': user.name,
        'user_type': user_type,
        'notifications': notifs,
        'unread_count': unread_count,
        'total_count': total_count,
        'read_count': read_count,
    }
    return render(request, 'notifications.html', context)


def seller_approve_item(request, item_id):
    """Seller approves an order item. If ALL items approved → order Confirmed + deduct inventory."""
    if request.method != 'POST':
        return redirect('notifications')

    user, user_type = _get_valid_session_user(request)
    if not user or user_type != 'seller':
        messages.error(request, 'Only sellers can approve order items.')
        return redirect('signin_page')

    try:
        order_item = OrderItem.objects.select_related('product', 'order').get(
            id=item_id, product__seller=user
        )
    except OrderItem.DoesNotExist:
        messages.error(request, 'Order item not found or you do not have permission.')
        return redirect('notifications')

    if order_item.status != 'Pending':
        messages.error(request, f'This item has already been {order_item.status.lower()}.')
        return redirect('notifications')

    order = order_item.order

    # Reject if order is already Rejected
    if order.status == 'Rejected':
        messages.error(request, 'This order has already been rejected.')
        return redirect('notifications')

    with transaction.atomic():
        # Approve this item
        order_item.status = 'Approved'
        order_item.save()

        # Mark the seller's approval-request notification as read
        Notification.objects.filter(
            seller=user, order_item=order_item, notification_type='approval_request'
        ).update(is_read=True)

        # Notify the buyer about this item's approval
        Notification.objects.create(
            buyer=order.buyer,
            order=order,
            order_item=order_item,
            notification_type='item_approved',
            message=(
                f"Seller {user.name} has approved '{order_item.product.name}' "
                f"(×{order_item.quantity}) in your order #{order.id}."
            ),
        )

        # Check if ALL items in this order are now Approved
        all_items = list(order.items.select_related('product__seller').all())
        all_approved = all(item.status == 'Approved' for item in all_items)

        if all_approved:
            order.status = 'Confirmed'
            order.save()

            # Deduct inventory NOW — atomically using F() expressions
            for item in all_items:
                Inventory.objects.filter(product=item.product).update(
                    quantity=F('quantity') - item.quantity
                )

            # ── WALLET: Credit each seller their portion ──
            seller_totals = {}  # seller_id → total amount
            for item in all_items:
                sid = item.product.seller_id
                seller_totals[sid] = seller_totals.get(sid, Decimal('0')) + item.line_total

            for sid, amount in seller_totals.items():
                seller_obj = Seller.objects.get(id=sid)
                seller_wallet = _get_or_create_wallet(seller_obj)
                seller_wallet.balance += amount
                seller_wallet.save()
                Transaction.objects.create(
                    wallet=seller_wallet,
                    order=order,
                    transaction_type='credit',
                    amount=amount,
                    balance_after=seller_wallet.balance,
                    description=f"Payment received for order #{order.id} — all sellers approved",
                )
                Notification.objects.create(
                    seller_id=sid,
                    order=order,
                    notification_type='wallet_credited',
                    message=(
                        f"₹{amount} has been credited to your wallet for order #{order.id}. "
                        f"All sellers approved — escrow released."
                    ),
                )

            # Notify buyer of full confirmation
            Notification.objects.create(
                buyer=order.buyer,
                order=order,
                notification_type='order_confirmed',
                message=(
                    f"Great news! All sellers have approved your order #{order.id}. "
                    f"Your order is now confirmed and being processed. Total: ₹{order.total_amount}."
                ),
            )

    messages.success(request, f'You approved "{order_item.product.name}" for order #{order.id}.')
    return redirect('notifications')


def seller_reject_item(request, item_id):
    """Seller rejects an order item → entire order gets Rejected."""
    if request.method != 'POST':
        return redirect('notifications')

    user, user_type = _get_valid_session_user(request)
    if not user or user_type != 'seller':
        messages.error(request, 'Only sellers can reject order items.')
        return redirect('signin_page')

    try:
        order_item = OrderItem.objects.select_related('product', 'order__buyer').get(
            id=item_id, product__seller=user
        )
    except OrderItem.DoesNotExist:
        messages.error(request, 'Order item not found or you do not have permission.')
        return redirect('notifications')

    if order_item.status != 'Pending':
        messages.error(request, f'This item has already been {order_item.status.lower()}.')
        return redirect('notifications')

    order = order_item.order

    with transaction.atomic():
        # Reject this particular item
        order_item.status = 'Rejected'
        order_item.save()

        # Reject the ENTIRE order
        order.status = 'Rejected'
        order.save()

        # Mark ALL remaining pending items in this order as Rejected
        order.items.filter(status='Pending').update(status='Rejected')

        # ── WALLET: Refund the buyer ──
        buyer_wallet = _get_or_create_wallet(order.buyer)
        buyer_wallet.balance += order.total_amount
        buyer_wallet.save()
        Transaction.objects.create(
            wallet=buyer_wallet,
            order=order,
            transaction_type='refund',
            amount=order.total_amount,
            balance_after=buyer_wallet.balance,
            description=(
                f"Refund for rejected order #{order.id} — "
                f"seller {user.name} declined '{order_item.product.name}'"
            ),
        )

        # Mark the seller's approval-request notification as read
        Notification.objects.filter(
            seller=user, order_item=order_item, notification_type='approval_request'
        ).update(is_read=True)

        # Mark all other sellers' pending approval requests for this order as read
        # since the order is now rejected
        Notification.objects.filter(
            order=order, notification_type='approval_request', is_read=False
        ).update(is_read=True)

        # Notify the buyer that the order was rejected and refunded
        Notification.objects.create(
            buyer=order.buyer,
            order=order,
            order_item=order_item,
            notification_type='order_rejected',
            message=(
                f"Your order #{order.id} has been rejected because seller "
                f"{user.name} declined the item '{order_item.product.name}'. "
                f"The entire order has been cancelled."
            ),
        )
        Notification.objects.create(
            buyer=order.buyer,
            order=order,
            notification_type='wallet_refunded',
            message=(
                f"₹{order.total_amount} has been refunded to your wallet "
                f"for rejected order #{order.id}."
            ),
        )

        # Notify other sellers that the order was cancelled (so they don't wait)
        other_seller_notifs = Notification.objects.filter(
            order=order,
            notification_type='approval_request',
        ).exclude(seller=user).values_list('seller_id', flat=True).distinct()

        for other_seller_id in other_seller_notifs:
            Notification.objects.create(
                seller_id=other_seller_id,
                order=order,
                notification_type='order_rejected',
                message=(
                    f"Order #{order.id} has been cancelled because another seller "
                    f"rejected an item. No further action is needed from you."
                ),
            )

    messages.success(
        request,
        f'You rejected "{order_item.product.name}". Order #{order.id} has been cancelled and buyer refunded.'
    )
    return redirect('notifications')


def mark_notification_read(request, notification_id):
    """Mark a single notification as read."""
    if request.method != 'POST':
        return redirect('notifications')

    user, user_type = _get_valid_session_user(request)
    if not user:
        return redirect('signin_page')

    if user_type == 'buyer':
        Notification.objects.filter(id=notification_id, buyer=user).update(is_read=True)
    elif user_type == 'seller':
        Notification.objects.filter(id=notification_id, seller=user).update(is_read=True)

    return redirect('notifications')


def mark_all_notifications_read(request):
    """Mark all notifications as read for the current user."""
    if request.method != 'POST':
        return redirect('notifications')

    user, user_type = _get_valid_session_user(request)
    if not user:
        return redirect('signin_page')

    if user_type == 'buyer':
        Notification.objects.filter(buyer=user, is_read=False).update(is_read=True)
    elif user_type == 'seller':
        Notification.objects.filter(seller=user, is_read=False).update(is_read=True)

    messages.success(request, 'All notifications marked as read.')
    return redirect('notifications')


# ──────────────────────────────────────────────────────────────
# WALLET VIEWS
# ──────────────────────────────────────────────────────────────

def wallet_page(request):
    """Wallet page for both buyers and sellers."""
    user, user_type = _get_valid_session_user(request)
    if not user:
        messages.error(request, 'Please sign in to view your wallet.')
        return redirect('signin_page')

    # Get or create wallet
    user_wallet = _get_or_create_wallet(user)

    transactions = user_wallet.transactions.select_related('order').all()

    # Compute stats
    total_credits = sum(
        t.amount for t in transactions if t.transaction_type in ('credit', 'refund', 'add_funds')
    )
    total_debits = sum(
        t.amount for t in transactions if t.transaction_type == 'debit'
    )

    context = {
        'user_name': user.name,
        'user_type': user_type,
        'wallet': user_wallet,
        'transactions': transactions,
        'total_credits': total_credits,
        'total_debits': total_debits,
        'txn_count': transactions.count(),
        'unread_notification_count': _get_unread_notification_count(request),
    }
    return render(request, 'wallet.html', context)


def add_funds(request):
    """POST-only: add ₹10,000 to the user's wallet."""
    if request.method != 'POST':
        return redirect('wallet')

    user, user_type = _get_valid_session_user(request)
    if not user:
        return redirect('signin_page')

    amount = Decimal('10000.00')

    with transaction.atomic():
        user_wallet = _get_or_create_wallet(user)

        user_wallet.balance += amount
        user_wallet.save()

        Transaction.objects.create(
            wallet=user_wallet,
            transaction_type='add_funds',
            amount=amount,
            balance_after=user_wallet.balance,
            description='Added ₹10,000 to wallet',
        )

    messages.success(request, '₹10,000 added to your wallet!')
    return redirect('wallet')

    # ──────────────────────────────────────────────────────────────
# FORGOT / RESET PASSWORD VIEWS
# Add these functions to the bottom of core/views.py
# ──────────────────────────────────────────────────────────────

def forgot_password(request):
    """
    Step 1: User enters their email + user type.
    If found, store the user identity in session and redirect to reset page.
    """
    if request.method == 'POST':
        email     = request.POST.get('email', '').strip().lower()
        user_type = request.POST.get('user_type', '').strip().lower()

        if not email or user_type not in ('buyer', 'seller'):
            messages.error(request, 'Please enter your email and select account type.')
            return render(request, 'forgot_password.html')

        user_model = _get_user_model(user_type)
        user = user_model.objects.filter(email=email).first()

        if not user:
            # Don't reveal whether account exists — show same message either way
            messages.error(request, 'No account found with that email and account type.')
            return render(request, 'forgot_password.html')

        # Store reset intent in session (not a full login)
        request.session['reset_user_id']   = user.id
        request.session['reset_user_type'] = user_type
        messages.success(request, f'Account found. Please set your new password.')
        return redirect('reset_password')

    return render(request, 'forgot_password.html')


def reset_password(request):
    """
    Step 2: User sets a new password.
    Requires reset_user_id + reset_user_type to be in session (set by forgot_password).
    """
    reset_id   = request.session.get('reset_user_id')
    reset_type = request.session.get('reset_user_type')

    # Guard: must have come through forgot_password first
    if not reset_id or not reset_type:
        messages.error(request, 'Please start from the forgot password page.')
        return redirect('forgot_password')

    if request.method == 'POST':
        new_password     = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not new_password or not confirm_password:
            messages.error(request, 'Both fields are required.')
        elif len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        elif new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        else:
            user_model = _get_user_model(reset_type)
            user = user_model.objects.filter(id=reset_id).first()

            if not user:
                messages.error(request, 'Account not found. Please try again.')
                # Clear stale session keys
                request.session.pop('reset_user_id', None)
                request.session.pop('reset_user_type', None)
                return redirect('forgot_password')

            user.password = make_password(new_password)
            user.save()

            # Clear reset session keys
            request.session.pop('reset_user_id', None)
            request.session.pop('reset_user_type', None)

            messages.success(request, 'Password reset successfully! Please sign in.')
            return redirect('signin_page')

    return render(request, 'reset_password.html')