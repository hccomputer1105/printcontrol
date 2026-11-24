from datetime import timedelta, date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from .models import PerfilUsuario, Empresa, Departamento
from .forms import NuevoUsuarioEmpresaForm, EditarUsuarioEmpresaForm
from monitoreo.models import Impresora
from monitoreo.views import obtener_datos_empresa
from monitoreo.models import Impresora, RegistroImpresion

@login_required
def gestionar_departamentos(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    empresa_destino = empresa or Empresa.objects.first()
    departamentos = Departamento.objects.all() if not empresa else Departamento.objects.filter(empresa=empresa)

    if request.method == 'POST' and empresa_destino:
        nombre = request.POST.get('nombre')
        lim_bn = int(request.POST.get('limite_bn_mensual', 2000))
        lim_color = int(request.POST.get('limite_color_mensual', 500))
        Departamento.objects.create(
            empresa=empresa_destino,
            nombre=nombre,
            limite_bn_mensual=lim_bn,
            limite_color_mensual=lim_color
        )
        messages.success(request, f"Departamento '{nombre}' creado correctamente.")
        return redirect('gestionar_departamentos')

    return render(request, 'empresas/departamentos.html', {
        'seccion_activa': 'departamentos',
        'empresa': empresa,
        'empresa_destino': empresa_destino,
        'dias_restantes': dias_restantes,
        'departamentos': departamentos
    })


@login_required
def actualizar_tarifas(request):
    empresa, vigente, _ = obtener_datos_empresa(request.user)
    if request.method == 'POST':
        empresa_id = request.POST.get('empresa_id')
        emp_target = get_object_or_404(Empresa, id=empresa_id) if empresa_id else empresa
        if emp_target:
            emp_target.costo_pagina_bn = request.POST.get('costo_pagina_bn', 0.03)
            emp_target.costo_pagina_color = request.POST.get('costo_pagina_color', 0.15)
            emp_target.max_paginas_por_trabajo = int(request.POST.get('max_paginas_por_trabajo', 0))
            emp_target.bloquear_color_web_correo = request.POST.get('bloquear_color_web_correo') == 'on'
            emp_target.save()
            messages.success(request, f"Tarifas y Reglas Inteligentes actualizadas para '{emp_target.nombre}'.")
    return redirect('gestionar_departamentos')


@login_required
def alternar_bloqueo_departamento(request, depto_id):
    depto = get_object_or_404(Departamento, id=depto_id)
    depto.bloqueado = not depto.bloqueado
    depto.save()
    return redirect('gestionar_departamentos')


@login_required
def reiniciar_cuota_departamento(request, depto_id):
    depto = get_object_or_404(Departamento, id=depto_id)
    depto.impresiones_bn_mes = 0
    depto.impresiones_color_mes = 0
    depto.save()
    messages.success(request, f"Contadores reiniciados para el departamento {depto.nombre}.")
    return redirect('gestionar_departamentos')


@login_required
def gestionar_usuarios(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    perfil_actual = getattr(request.user, 'perfil', None)
    if not request.user.is_superuser and (not perfil_actual or perfil_actual.rol not in ['SUPERADMIN', 'ADMIN_EMPRESA']):
        messages.error(request, "No tienes permisos para esta sección.")
        return redirect('dashboard')

    usuarios = PerfilUsuario.objects.all() if not empresa else PerfilUsuario.objects.filter(empresa=empresa)
    empresa_destino = empresa or Empresa.objects.first()

    if request.method == 'POST':
        form = NuevoUsuarioEmpresaForm(request.POST, empresa=empresa_destino)
        if form.is_valid() and empresa_destino:
            nuevo_user = User.objects.create_user(
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password']
            )
            PerfilUsuario.objects.create(
                user=nuevo_user,
                empresa=empresa_destino,
                departamento=form.cleaned_data['departamento'],
                rol=form.cleaned_data['rol'],
                usuario_sistema_operativo=form.cleaned_data['usuario_sistema_operativo'],
                limite_total_mensual=form.cleaned_data['limite_total_mensual'],
                limite_bn_mensual=form.cleaned_data['limite_bn_mensual'],
                limite_color_mensual=form.cleaned_data['limite_color_mensual'],
                requiere_pin_impresion=form.cleaned_data['requiere_pin_impresion'],
                pin_impresion=form.cleaned_data['pin_impresion']
            )
            messages.success(request, f"Usuario '{nuevo_user.username}' creado.")
            return redirect('gestionar_usuarios')
    else:
        form = NuevoUsuarioEmpresaForm(empresa=empresa_destino)

    return render(request, 'empresas/gestionar_usuarios.html', {
        'seccion_activa': 'usuarios',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'usuarios': usuarios,
        'form': form,
    })


@login_required
def editar_usuario(request, perfil_id):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    perfil_target = get_object_or_404(PerfilUsuario, id=perfil_id)

    if request.method == 'POST':
        form = EditarUsuarioEmpresaForm(request.POST, empresa=perfil_target.empresa)
        if form.is_valid():
            perfil_target.departamento = form.cleaned_data['departamento']
            perfil_target.rol = form.cleaned_data['rol']
            perfil_target.limite_total_mensual = form.cleaned_data['limite_total_mensual']
            perfil_target.limite_bn_mensual = form.cleaned_data['limite_bn_mensual']
            perfil_target.limite_color_mensual = form.cleaned_data['limite_color_mensual']
            perfil_target.requiere_pin_impresion = form.cleaned_data['requiere_pin_impresion']
            perfil_target.pin_impresion = form.cleaned_data['pin_impresion']
            perfil_target.save()

            nueva_clave = form.cleaned_data.get('nueva_password')
            if nueva_clave:
                perfil_target.user.set_password(nueva_clave)
                perfil_target.user.save()

            messages.success(request, f"Configuración actualizada para '{perfil_target.usuario_sistema_operativo}'.")
            return redirect('gestionar_usuarios')
    else:
        form = EditarUsuarioEmpresaForm(
            empresa=perfil_target.empresa,
            initial={
                'departamento': perfil_target.departamento,
                'rol': perfil_target.rol,
                'limite_total_mensual': perfil_target.limite_total_mensual,
                'limite_bn_mensual': perfil_target.limite_bn_mensual,
                'limite_color_mensual': perfil_target.limite_color_mensual,
                'requiere_pin_impresion': perfil_target.requiere_pin_impresion,
                'pin_impresion': perfil_target.pin_impresion,
            }
        )

    return render(request, 'empresas/editar_usuario.html', {
        'seccion_activa': 'usuarios',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'perfil_target': perfil_target,
        'form': form,
    })


@login_required
def gestionar_licencias(request):
    if not request.user.is_superuser:
        return redirect('dashboard')
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        identificacion = request.POST.get('identificacion')
        dias = int(request.POST.get('dias', 365))
        Empresa.objects.create(
            nombre=nombre,
            identificacion=identificacion,
            fecha_vencimiento=date.today() + timedelta(days=dias)
        )
        messages.success(request, f"Empresa '{nombre}' creada con licencia de {dias} días.")
        return redirect('gestionar_licencias')

    empresas = Empresa.objects.all().order_by('-fecha_registro')
    return render(request, 'empresas/licencias.html', {
        'seccion_activa': 'licencias',
        'dias_restantes': 9999,
        'empresas': empresas
    })


@login_required
def renovar_licencia(request, empresa_id):
    if not request.user.is_superuser:
        return redirect('dashboard')
    emp = get_object_or_404(Empresa, id=empresa_id)
    base = emp.fecha_vencimiento if emp.fecha_vencimiento > date.today() else date.today()
    emp.fecha_vencimiento = base + timedelta(days=365)
    emp.activa = True
    emp.save()
    return redirect('gestionar_licencias')


@login_required
def alternar_bloqueo_usuario(request, perfil_id):
    perfil_target = get_object_or_404(PerfilUsuario, id=perfil_id)
    perfil_target.bloqueado_manualmente = not perfil_target.bloqueado_manualmente
    perfil_target.save()
    return redirect('gestionar_usuarios')


@login_required
def reiniciar_cuota_usuario(request, perfil_id):
    perfil_target = get_object_or_404(PerfilUsuario, id=perfil_id)
    perfil_target.impresiones_bn_mes = 0
    perfil_target.impresiones_color_mes = 0
    perfil_target.save()
    return redirect('gestionar_usuarios')


@login_required
def alternar_bloqueo_impresora(request, impresora_id):
    impresora = get_object_or_404(Impresora, id=impresora_id)
    impresora.bloqueada_globalmente = not impresora.bloqueada_globalmente
    impresora.save()
    return redirect('lista_impresoras')


@login_required
def alternar_control_impresora(request, impresora_id):
    impresora = get_object_or_404(Impresora, id=impresora_id)
    impresora.control_activo = not impresora.control_activo
    impresora.save()
    estado_texto = "activado" if impresora.control_activo else "desactivado (paso libre)"
    messages.success(request, f"Control de impresión {estado_texto} para '{impresora.nombre_cola}'.")
    return redirect('lista_impresoras')

@login_required
def portal_empleado(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    perfil = getattr(request.user, 'perfil', None)
    if not perfil:
        messages.info(request, "Tu usuario es administrador global y no tiene un perfil de empleado asociado.")
        return redirect('dashboard')

    # Procesar actualización de PIN o contraseña web por parte del propio empleado
    if request.method == 'POST':
        nuevo_pin = request.POST.get('pin_impresion', '').strip()
        nueva_clave = request.POST.get('nueva_password', '').strip()

        if nuevo_pin:
            if not nuevo_pin.isdigit() or not (4 <= len(nuevo_pin) <= 6):
                messages.error(request, "El PIN debe contener entre 4 y 6 dígitos numéricos.")
                return redirect('portal_empleado')
            perfil.pin_impresion = nuevo_pin
            perfil.save()
            messages.success(request, "Tu PIN de impresión ha sido actualizado correctamente.")

        if nueva_clave:
            if len(nueva_clave) < 6:
                messages.error(request, "La nueva contraseña web debe tener al menos 6 caracteres.")
                return redirect('portal_empleado')
            request.user.set_password(nueva_clave)
            request.user.save()
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)
            messages.success(request, "Tu contraseña de acceso web ha sido actualizada.")

        return redirect('portal_empleado')

    # Calcular porcentajes de consumo del usuario
    total_usado_mixto = perfil.impresiones_bn_mes + perfil.impresiones_color_mes
    pct_mixto = min(100, int((total_usado_mixto / perfil.limite_total_mensual) * 100)) if perfil.limite_total_mensual > 0 else 0
    pct_bn = min(100, int((perfil.impresiones_bn_mes / perfil.limite_bn_mensual) * 100)) if perfil.limite_bn_mensual > 0 else 0
    pct_color = min(100, int((perfil.impresiones_color_mes / perfil.limite_color_mensual) * 100)) if perfil.limite_color_mensual > 0 else 0

    mis_trabajos = RegistroImpresion.objects.filter(
        empresa=perfil.empresa,
        usuario_so=perfil.usuario_sistema_operativo
    )[:30]

    return render(request, 'empresas/portal_empleado.html', {
        'seccion_activa': 'mi_portal',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'perfil': perfil,
        'total_usado_mixto': total_usado_mixto,
        'pct_mixto': pct_mixto,
        'pct_bn': pct_bn,
        'pct_color': pct_color,
        'mis_trabajos': mis_trabajos,
    })