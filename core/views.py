from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
import json

# Signup endpoint
@csrf_exempt
@require_http_methods(["POST"])
def signup(request):
    """
    Signup endpoint
    Expects JSON: {
        "username": "string",
        "email": "string",
        "password": "string"
    }
    """
    try:
        data = json.loads(request.body)
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        # Validation
        if not all([username, email, password]):
            return JsonResponse({
                'success': False,
                'message': 'Missing required fields: username, email, password'
            }, status=400)
        
        # Check if user already exists
        if User.objects.filter(username=username).exists():
            return JsonResponse({
                'success': False,
                'message': 'Username already taken'
            }, status=400)
        
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'message': 'Email already registered'
            }, status=400)
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        
        return JsonResponse({
            'success': True,
            'message': 'User created successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email
            }
        }, status=201)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON format'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)


# Signin endpoint
@csrf_exempt
@require_http_methods(["POST"])
def signin(request):
    """
    Signin endpoint
    Expects JSON: {
        "username": "string",
        "password": "string"
    }
    """
    try:
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')
        
        # Validation
        if not all([username, password]):
            return JsonResponse({
                'success': False,
                'message': 'Missing required fields: username, password'
            }, status=400)
        
        # Authenticate user
        user = authenticate(request, username=username, password=password)
        
        if user is None:
            return JsonResponse({
                'success': False,
                'message': 'Invalid username or password'
            }, status=401)
        
        # Login user
        login(request, user)
        
        return JsonResponse({
            'success': True,
            'message': 'Logged in successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email
            }
        }, status=200)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON format'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)


# Signout endpoint
@csrf_exempt
@require_http_methods(["POST"])
def signout(request):
    """
    Signout endpoint
    No payload required
    """
    try:
        logout(request)
        return JsonResponse({
            'success': True,
            'message': 'Logged out successfully'
        }, status=200)
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)
