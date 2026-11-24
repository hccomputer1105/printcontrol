from django.db import models
from empresas.models import Empresa, Departamento


class Equipo(models.Model):
    SISTEMAS_OPERATIVOS = (
        ('WINDOWS', 'Windows'),
        ('LINUX', 'Linux'),
        ('MACOS', 'macOS'),
    )

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='equipos')
    nombre_host = models.CharField(max_length=150, verbose_name="Nombre de la PC (Hostname)")
    sistema_operativo = models.CharField(max_length=20, choices=SISTEMAS_OPERATIVOS, default='WINDOWS')
    direccion_ip = models.GenericIPAddressField(null=True, blank=True)
    agente_activo = models.BooleanField(default=True)
    ultima_conexion = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('empresa', 'nombre_host')

    def __str__(self):
        return f"{self.nombre_host} ({self.sistema_operativo}) - {self.empresa.nombre}"


class Impresora(models.Model):
    MARCAS = (
        ('HP', 'HP'),
        ('LEXMARK', 'Lexmark'),
        ('SHARP', 'Sharp'),
        ('RICOH', 'Ricoh'),
        ('XEROX', 'Xerox'),
        ('CANON', 'Canon'),
        ('BROTHER', 'Brother'),
        ('EPSON', 'Epson'),
        ('KYOCERA', 'Kyocera'),
        ('KONICA_MINOLTA', 'Konica Minolta'),
        ('SAMSUNG', 'Samsung'),
        ('TOSHIBA', 'Toshiba'),
        ('OKI', 'OKI'),
        ('PANTUM', 'Pantum'),
        ('ZEBRA', 'Zebra'),
        ('OTRA', 'Otra Marca'),
    )

    ESTADOS = (
        ('ONLINE', 'En Línea / Lista'),
        ('OFFLINE', 'Desconectada / Apagada'),
        ('ERROR', 'Error / Sin Papel / Atascos'),
    )

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='impresoras')
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='impresoras_conectadas')
    nombre_cola = models.CharField(max_length=200, verbose_name="Nombre en el Sistema")
    marca = models.CharField(max_length=30, choices=MARCAS, default='OTRA')
    modelo = models.CharField(max_length=100, blank=True, null=True)
    puerto_o_ip = models.CharField(max_length=100, blank=True, null=True, verbose_name="Puerto USB o IP")
    es_color = models.BooleanField(default=False, verbose_name="Soporta Color")
    estado = models.CharField(max_length=20, choices=ESTADOS, default='ONLINE')
    bloqueada_globalmente = models.BooleanField(default=False, verbose_name="Bloquear esta impresora para todos")
    control_activo = models.BooleanField(
        default=True,
        verbose_name="Control y Monitoreo Activo (False = Impresión libre sin restricciones)"
    )

    # Telemetría SNMP (Página de prueba y contadores de copias)
    ip_impresora = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP Real en Red")
    numero_serie = models.CharField(max_length=100, blank=True, null=True, verbose_name="Serial de Fábrica")
    contador_total_fabrica = models.PositiveIntegerField(default=0, verbose_name="Contador Total Histórico")
    contador_copias_bn = models.PositiveIntegerField(default=0, verbose_name="Contador Copias B/N Fábrica")
    contador_copias_color = models.PositiveIntegerField(default=0, verbose_name="Contador Copias Color Fábrica")
    toner_negro = models.IntegerField(default=-1, verbose_name="% Tóner Negro (-1 = no disponible)")
    toner_cian = models.IntegerField(default=-1, verbose_name="% Tóner Cian")
    toner_magenta = models.IntegerField(default=-1, verbose_name="% Tóner Magenta")
    toner_amarillo = models.IntegerField(default=-1, verbose_name="% Tóner Amarillo")

    def __str__(self):
        return f"{self.get_marca_display()} - {self.nombre_cola} ({self.equipo.nombre_host})"


class RegistroImpresion(models.Model):
    TIPOS_IMPRESION = (
        ('BN', 'Blanco y Negro'),
        ('COLOR', 'Color'),
    )

    ESTADOS_TRABAJO = (
        ('IMPRESO', 'Impreso Correctamente'),
        ('ESPERANDO_PIN', 'Retenido (Esperando PIN de Usuario)'),
        ('BLOQUEADO_REGLA', 'Bloqueado (Regla Inteligente de Ahorro)'),
        ('BLOQUEADO_DEPTO', 'Bloqueado (Cuota de Departamento Excedida)'),
        ('BLOQUEADO_CUOTA', 'Bloqueado (Cuota Individual Excedida)'),
        ('BLOQUEADO_ADMIN', 'Bloqueado por Administrador'),
        ('CANCELADO', 'Cancelado por el Usuario'),
    )

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='registros')
    departamento = models.ForeignKey(Departamento, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Departamento")
    equipo = models.ForeignKey(Equipo, on_delete=models.SET_NULL, null=True)
    impresora = models.ForeignKey(Impresora, on_delete=models.SET_NULL, null=True)
    usuario_so = models.CharField(max_length=100, verbose_name="Usuario PC")
    nombre_documento = models.CharField(max_length=255, default="Documento sin título")
    paginas = models.PositiveIntegerField(default=1)
    costo_total = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="Costo Total ($)")
    tipo_impresion = models.CharField(max_length=10, choices=TIPOS_IMPRESION, default='BN')
    estado = models.CharField(max_length=20, choices=ESTADOS_TRABAJO, default='IMPRESO')
    fecha_impresion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_impresion']

    def __str__(self):
        return f"{self.usuario_so} - {self.nombre_documento} ({self.paginas} págs - {self.estado})"


class RegistroCopia(models.Model):
    TIPOS_COPIA = (
        ('BN', 'Blanco y Negro'),
        ('COLOR', 'Color'),
    )

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='copias')
    impresora = models.ForeignKey(Impresora, on_delete=models.CASCADE, related_name='copias_realizadas')
    usuario_panel = models.CharField(max_length=100, default='Panel Físico (Sin PIN)', verbose_name="Usuario / Código Panel")
    cantidad = models.PositiveIntegerField(default=1)
    tipo_copia = models.CharField(max_length=10, choices=TIPOS_COPIA, default='BN')
    costo_total = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_registro']

    def __str__(self):
        return f"Copia ({self.cantidad} {self.tipo_copia}) - {self.impresora.nombre_cola}"