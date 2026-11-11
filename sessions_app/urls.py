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
    path(
        "sessions/<uuid:pk>/photos/<uuid:photo_id>/",
        views.rep_photo_image,
        name="rep_photo_image",
    ),
    path("j/<str:token>/", views.customer_join, name="customer_join"),
    path("c/", views.customer_capture, name="customer_capture"),
    path("c/upload/", views.customer_upload, name="customer_upload"),
    path("c/photos/", views.customer_photos, name="customer_photos"),
    path(
        "c/photos/<uuid:photo_id>/",
        views.customer_photo_image,
        name="customer_photo_image",
    ),
    path(
        "c/photos/<uuid:photo_id>/delete/",
        views.customer_photo_delete,
        name="customer_photo_delete",
    ),
]
