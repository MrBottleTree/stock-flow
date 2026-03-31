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
    path('items/<int:product_id>/', views.item_detail, name='item_detail'),
    path('items/sold-out/', views.sold_out_items, name='sold_out_items'),
    path('inventory/', views.inventory, name='inventory'),
    path('inventory/edit/<int:product_id>/', views.inventory, name='edit_inventory'),
    path('add-address/', views.add_address, name='add_address'),


    path('orders/', views.order_history, name='order_history'),
 path('profile/',                              views.profile,             name='profile'),
path('profile/update/',                       views.update_profile,      name='update_profile'),
path('profile/change-password/',              views.change_password,     name='change_password'),
path('profile/delete-account/',               views.delete_account,      name='delete_account'),
path('orders/<int:order_id>/delete/',         views.delete_order,        name='delete_order'),
path('addresses/<int:address_id>/delete/',    views.delete_address,      name='delete_address'),
path('addresses/<int:address_id>/default/',   views.set_default_address, name='set_default_address'),

    path('cart/',     views.cart,     name='cart'),
    path('checkout/', views.checkout, name='checkout'),
]