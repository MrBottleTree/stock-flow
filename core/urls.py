from django.urls import path
from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('signin/', views.signin,  name='signin'),
    path('signup/', views.signup,  name='signup'),
    path('signout/', views.signout, name='signout'),

    # Abhi this is just dummy in the views.py, change it when needed
    path('products/', views.products, name='products'),
    path('inventory/', views.inventory, name='inventory'),
    path('add-address/', views.add_address, name='add_address'),
]