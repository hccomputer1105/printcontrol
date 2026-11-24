from django import forms
from .models import Departamento

class NuevoUsuarioEmpresaForm(forms.Form):
    username = forms.CharField(label="Usuario de Acceso Web", max_length=100, widget=forms.TextInput(attrs={'class': 'form-control form-control-sm'}))
    password = forms.CharField(label="Contraseña Web", widget=forms.PasswordInput(attrs={'class': 'form-control form-control-sm'}))
    departamento = forms.ModelChoiceField(
        label="Departamento / Centro de Costos",
        queryset=Departamento.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    rol = forms.ChoiceField(label="Rol en el Sistema", choices=[
        ('ADMIN_EMPRESA', 'Administrador de Empresa'),
        ('SUPERVISOR', 'Supervisor (Solo Lectura)'),
        ('EMPLEADO', 'Empleado / Usuario Final'),
    ], widget=forms.Select(attrs={'class': 'form-select form-select-sm'}))
    usuario_sistema_operativo = forms.CharField(
        label="Usuario en Windows / Linux (whoami)",
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: hreyes'})
    )
    limite_bn_mensual = forms.IntegerField(label="Límite Usuario B/N (0 = ilimitado)", initial=500, min_value=0, widget=forms.NumberInput(attrs={'class': 'form-control form-control-sm'}))
    limite_color_mensual = forms.IntegerField(label="Límite Usuario Color (0 = ilimitado)", initial=100, min_value=0, widget=forms.NumberInput(attrs={'class': 'form-control form-control-sm'}))
    requiere_pin_impresion = forms.BooleanField(label="Exigir PIN para imprimir", required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    pin_impresion = forms.CharField(label="PIN (4-6 dígitos)", max_length=10, required=False, widget=forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: 1234'}))

    limite_total_mensual = forms.IntegerField(
        label="Límite General Mixto B/N + Color (0 = desactivado)",
        initial=0, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-sm'})
    )

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields['departamento'].queryset = Departamento.objects.filter(empresa=empresa)
        else:
            self.fields['departamento'].queryset = Departamento.objects.all()


class EditarUsuarioEmpresaForm(forms.Form):
    departamento = forms.ModelChoiceField(
        label="Departamento / Centro de Costos",
        queryset=Departamento.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    rol = forms.ChoiceField(label="Rol en el Sistema", choices=[
        ('ADMIN_EMPRESA', 'Administrador de Empresa'),
        ('SUPERVISOR', 'Supervisor (Solo Lectura)'),
        ('EMPLEADO', 'Empleado / Usuario Final'),
    ], widget=forms.Select(attrs={'class': 'form-select form-select-sm'}))
    nueva_password = forms.CharField(
        label="Contraseña de Acceso Web (dejar en blanco para no cambiar)",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Nueva contraseña opcional'})
    )
    limite_bn_mensual = forms.IntegerField(label="Límite Usuario B/N (0 = ilimitado)", min_value=0, widget=forms.NumberInput(attrs={'class': 'form-control form-control-sm'}))
    limite_color_mensual = forms.IntegerField(label="Límite Usuario Color (0 = ilimitado)", min_value=0, widget=forms.NumberInput(attrs={'class': 'form-control form-control-sm'}))
    requiere_pin_impresion = forms.BooleanField(label="Exigir PIN para imprimir", required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    pin_impresion = forms.CharField(label="PIN (4-6 dígitos)", max_length=10, required=False, widget=forms.TextInput(attrs={'class': 'form-control form-control-sm'}))

    limite_total_mensual = forms.IntegerField(
        label="Límite General Mixto B/N + Color (0 = desactivado)",
        initial=0, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-sm'})
    )

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields['departamento'].queryset = Departamento.objects.filter(empresa=empresa)
        else:
            self.fields['departamento'].queryset = Departamento.objects.all()