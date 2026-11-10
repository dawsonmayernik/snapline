"""URL routes for support sessions and the customer join link."""

from django.urls import path

from . import views

app_name = "sessions_app"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sessions/new/", views.create_session, name="create_session"),
    path("sessions/<uuid:pk>/", views.session_detail, name="session_detail"),
    path("sessions/<uuid:pk>/link/", views.reissue_link, name="reissue_link"),
    path("sessions/<uuid:pk>/close/", views.close_session, name="close_session"),
    path("j/<str:token>/", views.customer_join, name="customer_join"),
    path("c/", views.customer_capture, name="customer_capture"),
]
