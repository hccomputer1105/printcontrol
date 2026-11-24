from django.contrib import admin
from .models import Equipo, Impresora, RegistroImpresion, RegistroCopia


@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ('nombre_host', 'empresa', 'sistema_operativo', 'direccion_ip', 'ultima_conexion', 'agente_activo')
    list_filter = ('empresa', 'sistema_operativo', 'agente_activo')
    search_fields = ('nombre_host', 'direccion_ip')


@admin.register(Impresora)
class ImpresoraAdmin(admin.ModelAdmin):
    list_display = ('nombre_cola', 'marca', 'equipo', 'empresa', 'ip_impresora', 'estado', 'control_activo', 'bloqueada_globalmente')
    list_filter = ('empresa', 'marca', 'estado', 'control_activo', 'bloqueada_globalmente')
    search_fields = ('nombre_cola', 'ip_impresora', 'numero_serie')


@admin.register(RegistroImpresion)
class RegistroImpresionAdmin(admin.ModelAdmin):
    list_display = ('usuario_so', 'nombre_documento', 'impresora', 'paginas', 'tipo_impresion', 'costo_total', 'estado', 'fecha_impresion')
    list_filter = ('empresa', 'estado', 'tipo_impresion', 'fecha_impresion')
    search_fields = ('usuario_so', 'nombre_documento')


@admin.register(RegistroCopia)
class RegistroCopiaAdmin(admin.ModelAdmin):
    list_display = ('impresora', 'usuario_panel', 'cantidad', 'tipo_copia', 'costo_total', 'fecha_registro')
    list_filter = ('empresa', 'tipo_copia', 'fecha_registro')
    search_fields = ('usuario_panel', 'impresora__nombre_cola')