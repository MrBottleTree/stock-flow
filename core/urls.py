from django.urls import path
from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('signin/', views.signin,  name='signin'),
    path('signup/', views.signup,  name='signup'),
    path('signout/', views.signout, name='signout'),

    path('auth/signin/', views.signin_page, name='signin_page'),
    path('auth/signup/', views.signup_page, name='signup_page'),
    path('auth/signout/', views.signout_page, name='signout_page'),

    # Abhi this is just dummy in the views.py, change it when needed
    path('products/', views.products, name='products'),
    path('items/', views.items, name='items'),
    path('inventory/', views.inventory, name='inventory'),
    path('add-address/', views.add_address, name='add_address'),


    path('orders/', views.order_history, name='order_history'),
]