from django.urls import path
from . import views

urlpatterns = [
    path('auth/signup/', views.signup, name='signup'),
    path('auth/signup', views.signup, name='signup_no_slash'),
    path('auth/signin/', views.signin, name='signin'),
    path('auth/signin', views.signin, name='signin_no_slash'),
    path('auth/signout/', views.signout, name='signout'),
    path('auth/signout', views.signout, name='signout_no_slash'),
]
