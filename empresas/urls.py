from django.urls import path
from . import views

urlpatterns = [
    path('departamentos/', views.gestionar_departamentos, name='gestionar_departamentos'),
    path('departamentos/<int:depto_id>/bloquear/', views.alternar_bloqueo_departamento, name='alternar_bloqueo_departamento'),
    path('departamentos/<int:depto_id>/reiniciar/', views.reiniciar_cuota_departamento, name='reiniciar_cuota_departamento'),
    path('usuarios/', views.gestionar_usuarios, name='gestionar_usuarios'),
    path('licencias/', views.gestionar_licencias, name='gestionar_licencias'),
    path('licencias/<int:empresa_id>/renovar/', views.renovar_licencia, name='renovar_licencia'),
    path('usuarios/<int:perfil_id>/bloquear/', views.alternar_bloqueo_usuario, name='alternar_bloqueo_usuario'),
    path('usuarios/<int:perfil_id>/reiniciar/', views.reiniciar_cuota_usuario, name='reiniciar_cuota_usuario'),
    path('impresoras/<int:impresora_id>/bloquear/', views.alternar_bloqueo_impresora, name='alternar_bloqueo_impresora'),
    path('usuarios/<int:perfil_id>/editar/', views.editar_usuario, name='editar_usuario'),
    path('tarifas/', views.actualizar_tarifas, name='actualizar_tarifas'),
    path('impresoras/<int:impresora_id>/control/', views.alternar_control_impresora, name='alternar_control_impresora'),
    path('mi-portal/', views.portal_empleado, name='portal_empleado'),
]