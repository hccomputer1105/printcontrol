import uuid
from datetime import date, timedelta
from django.db import models
from django.contrib.auth.models import User


def vencimiento_por_defecto():
    return date.today() + timedelta(days=365)


class Empresa(models.Model):
    nombre = models.CharField(max_length=150, verbose_name="Nombre de la Empresa")
    identificacion = models.CharField(max_length=50, unique=True, verbose_name="RIF / NIT / Tax ID")
    token_api = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    activa = models.BooleanField(default=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_vencimiento = models.DateField(default=vencimiento_por_defecto, verbose_name="Vencimiento de Licencia")

    # Tarifas por página ($)
    costo_pagina_bn = models.DecimalField(max_digits=6, decimal_places=4, default=0.0300, verbose_name="Costo Página B/N ($)")
    costo_pagina_color = models.DecimalField(max_digits=6, decimal_places=4, default=0.1500, verbose_name="Costo Página Color ($)")

    # Reglas inteligentes de ahorro
    max_paginas_por_trabajo = models.PositiveIntegerField(
        default=0,
        verbose_name="Máximo de páginas por documento (0 = sin límite)"
    )
    bloquear_color_web_correo = models.BooleanField(
        default=False,
        verbose_name="Bloquear impresión a COLOR desde navegadores y correos"
    )

    @property
    def dias_restantes(self):
        delta = (self.fecha_vencimiento - date.today()).days
        return max(delta, 0)

    @property
    def licencia_vigente(self):
        return self.activa and date.today() <= self.fecha_vencimiento

    def __str__(self):
        return f"{self.nombre} (Vence: {self.fecha_vencimiento})"


class Departamento(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='departamentos')
    nombre = models.CharField(max_length=100, verbose_name="Nombre del Departamento")
    
    bloqueado = models.BooleanField(default=False, verbose_name="Bloquear todo el departamento")
    limite_bn_mensual = models.PositiveIntegerField(default=2000, verbose_name="Límite Depto B/N (0 = ilimitado)")
    limite_color_mensual = models.PositiveIntegerField(default=500, verbose_name="Límite Depto Color (0 = ilimitado)")
    
    impresiones_bn_mes = models.PositiveIntegerField(default=0)
    impresiones_color_mes = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('empresa', 'nombre')

    def __str__(self):
        return f"{self.nombre} ({self.empresa.nombre})"


class PerfilUsuario(models.Model):
    ROLES = (
        ('SUPERADMIN', 'Super Administrador (Global)'),
        ('ADMIN_EMPRESA', 'Administrador de Empresa'),
        ('SUPERVISOR', 'Supervisor (Solo Lectura)'),
        ('EMPLEADO', 'Empleado / Usuario Final'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='usuarios')
    departamento = models.ForeignKey(Departamento, on_delete=models.SET_NULL, null=True, blank=True, related_name='miembros')
    rol = models.CharField(max_length=20, choices=ROLES, default='EMPLEADO')
    usuario_sistema_operativo = models.CharField(
        max_length=100,
        help_text="Nombre de usuario con el que inicia sesión en Windows o Linux (ej: hreyes)"
    )

    # Control de cuotas y bloqueo individual
    bloqueado_manualmente = models.BooleanField(default=False, verbose_name="Bloquear impresiones")
    requiere_pin_impresion = models.BooleanField(default=False, verbose_name="Exigir PIN para imprimir")
    pin_impresion = models.CharField(max_length=10, blank=True, null=True, verbose_name="PIN / Contraseña de impresión")

    limite_total_mensual = models.PositiveIntegerField(
        default=0,
        verbose_name="Límite General Mixto B/N + Color (0 = usar límites separados o ilimitado)"
    )
    limite_bn_mensual = models.PositiveIntegerField(default=500, verbose_name="Límite mensual Blanco y Negro (0 = ilimitado)")
    limite_color_mensual = models.PositiveIntegerField(default=100, verbose_name="Límite mensual Color (0 = ilimitado)")
    
    impresiones_bn_mes = models.PositiveIntegerField(default=0)
    impresiones_color_mes = models.PositiveIntegerField(default=0)

    def __str__(self):
        depto = self.departamento.nombre if self.departamento else "Sin Depto"
        return f"{self.user.username} [{depto}] - {self.empresa.nombre}"