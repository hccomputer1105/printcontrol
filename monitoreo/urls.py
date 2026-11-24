from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('impresoras/', views.lista_impresoras, name='lista_impresoras'),
    path('reportes/', views.reportes_vista, name='reportes_vista'),
    path('api/sincronizar/', views.sincronizar_equipo, name='api_sincronizar'),
    path('api/validar-impresion/', views.validar_y_registrar_impresion, name='api_validar_impresion'),
    path('copias/', views.lista_copias, name='lista_copias'),
]