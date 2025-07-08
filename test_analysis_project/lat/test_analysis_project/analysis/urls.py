from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('logs/<str:test_run_id>/', views.log_view, name='log_view'),
    path('manage/', views.manage_view, name='manage'),
]
