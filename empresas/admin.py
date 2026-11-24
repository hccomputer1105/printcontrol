from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Empresa, PerfilUsuario

@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'identificacion', 'token_api', 'activa')
    readonly_fields = ('token_api',)

@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ('user', 'empresa', 'rol', 'usuario_sistema_operativo', 'impresiones_bn_mes', 'limite_bn_mensual', 'impresiones_color_mes', 'limite_color_mensual', 'bloqueado_manualmente')
    list_filter = ('empresa', 'rol', 'bloqueado_manualmente')