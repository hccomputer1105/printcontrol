from datetime import timedelta
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from empresas.models import Empresa, PerfilUsuario
from .models import Equipo, Impresora, RegistroImpresion, RegistroCopia


def obtener_datos_empresa(user):
    """Retorna la empresa del usuario, si su licencia está vigente y los días restantes."""
    if user.is_superuser:
        return None, True, 9999
    perfil = getattr(user, 'perfil', None)
    if not perfil:
        return None, False, 0
    emp = perfil.empresa
    return emp, emp.licencia_vigente, emp.dias_restantes


def detectar_marca_automatica(nombre_cola):
    nombre = nombre_cola.upper()
    marcas = [
        'HP', 'HEWLETT', 'LEXMARK', 'SHARP', 'RICOH', 'XEROX', 'CANON',
        'BROTHER', 'EPSON', 'KYOCERA', 'KONICA', 'MINOLTA', 'SAMSUNG',
        'TOSHIBA', 'OKI', 'PANTUM', 'ZEBRA'
    ]
    for m in marcas:
        if m in nombre:
            if m == 'HEWLETT':
                return 'HP'
            if m in ['KONICA', 'MINOLTA']:
                return 'KONICA_MINOLTA'
            return m
    return 'OTRA'


def calcular_alertas_predictivas_toner(impresoras_qs):
    """
    Calcula el ritmo diario de impresión de cada máquina (últimos 30 días)
    y estima los días restantes de vida útil de cada cartucho de tóner.
    """
    alertas = []
    hace_30_dias = timezone.now() - timedelta(days=30)

    for imp in impresoras_qs:
        pags_30d = RegistroImpresion.objects.filter(
            impresora=imp,
            estado='IMPRESO',
            fecha_impresion__gte=hace_30_dias
        ).aggregate(total=Sum('paginas'))['total'] or 0

        promedio_diario = round(pags_30d / 30, 1) if pags_30d > 0 else 5.0
        rendimiento_cartucho = 3000

        suministros = [
            ('Negro (K)', imp.toner_negro, 'dark'),
            ('Cian (C)', imp.toner_cian, 'info'),
            ('Magenta (M)', imp.toner_magenta, 'danger'),
            ('Amarillo (Y)', imp.toner_amarillo, 'warning'),
        ]

        for nombre_color, porcentaje, badge_color in suministros:
            if porcentaje < 0 or porcentaje > 25:
                continue

            paginas_estimadas_restantes = int((porcentaje / 100.0) * rendimiento_cartucho)
            dias_restantes = max(1, int(paginas_estimadas_restantes / promedio_diario))
            nivel_urgencia = 'CRITICO' if porcentaje <= 15 else 'ADVERTENCIA'

            alertas.append({
                'impresora': imp,
                'color_nombre': nombre_color,
                'badge_color': badge_color,
                'porcentaje': porcentaje,
                'dias_restantes': dias_restantes,
                'promedio_diario': promedio_diario,
                'nivel_urgencia': nivel_urgencia,
            })

    alertas.sort(key=lambda x: x['porcentaje'])
    return alertas


# ==================== VISTAS DEL DASHBOARD WEB ====================

@login_required
def dashboard(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.rol == 'EMPLEADO':
        return redirect('portal_empleado')

    registros = RegistroImpresion.objects.all() if not empresa else RegistroImpresion.objects.filter(empresa=empresa)
    impresoras = Impresora.objects.all() if not empresa else Impresora.objects.filter(empresa=empresa)
    usuarios = PerfilUsuario.objects.all() if not empresa else PerfilUsuario.objects.filter(empresa=empresa)

    total_paginas = registros.filter(estado='IMPRESO').aggregate(total=Sum('paginas'))['total'] or 0
    total_bloqueados = registros.exclude(estado='IMPRESO').count()
    costo_total_mes = registros.filter(estado='IMPRESO').aggregate(total=Sum('costo_total'))['total'] or 0

    consumo_impresoras = registros.filter(estado='IMPRESO').values('impresora__nombre_cola').annotate(
        total=Sum('paginas')
    ).order_by('-total')[:6]

    alertas_toner = calcular_alertas_predictivas_toner(impresoras)

    return render(request, 'monitoreo/dashboard.html', {
        'seccion_activa': 'dashboard',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'total_paginas': total_paginas,
        'total_bloqueados': total_bloqueados,
        'costo_total_mes': costo_total_mes,
        'impresoras_activas': impresoras.filter(estado='ONLINE').count(),
        'ultimos_registros': registros[:12],
        'consumo_impresoras': list(consumo_impresoras),
        'usuarios': usuarios[:8],
        'alertas_toner': alertas_toner,
    })


@login_required
def lista_impresoras(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    impresoras = Impresora.objects.all() if not empresa else Impresora.objects.filter(empresa=empresa)
    return render(request, 'monitoreo/impresoras.html', {
        'seccion_activa': 'impresoras',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'impresoras': impresoras
    })


@login_required
def lista_copias(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    copias = RegistroCopia.objects.all() if not empresa else RegistroCopia.objects.filter(empresa=empresa)
    total_copias_bn = copias.filter(tipo_copia='BN').aggregate(t=Sum('cantidad'))['t'] or 0
    total_copias_color = copias.filter(tipo_copia='COLOR').aggregate(t=Sum('cantidad'))['t'] or 0
    costo_copias = copias.aggregate(t=Sum('costo_total'))['t'] or 0

    return render(request, 'monitoreo/copias.html', {
        'seccion_activa': 'copias',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'copias_lista': copias[:100],
        'total_copias_bn': total_copias_bn,
        'total_copias_color': total_copias_color,
        'costo_copias': costo_copias,
    })


@login_required
def reportes_vista(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    registros = RegistroImpresion.objects.all() if not empresa else RegistroImpresion.objects.filter(empresa=empresa)
    impresoras = Impresora.objects.all() if not empresa else Impresora.objects.filter(empresa=empresa)

    usuario_filtro = request.GET.get('usuario', '').strip()
    impresora_filtro = request.GET.get('impresora', '').strip()
    fecha_inicio = request.GET.get('fecha_inicio', '').strip()
    fecha_fin = request.GET.get('fecha_fin', '').strip()

    if usuario_filtro:
        registros = registros.filter(usuario_so__icontains=usuario_filtro)
    if impresora_filtro:
        registros = registros.filter(impresora_id=impresora_filtro)
    if fecha_inicio:
        registros = registros.filter(fecha_impresion__date__gte=fecha_inicio)
    if fecha_fin:
        registros = registros.filter(fecha_impresion__date__lte=fecha_fin)

    return render(request, 'monitoreo/reportes.html', {
        'seccion_activa': 'reportes',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'registros': registros[:200],
        'impresoras': impresoras,
        'filtros': {
            'usuario': usuario_filtro,
            'impresora': impresora_filtro,
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
        }
    })


# ==================== API PARA LOS AGENTES DE PC ====================

@api_view(['POST'])
def sincronizar_equipo(request):
    token = request.data.get('token_api')
    empresa = Empresa.objects.filter(token_api=token).first()
    if not empresa:
        return Response({"error": "Token inválido"}, status=status.HTTP_401_UNAUTHORIZED)

    if not empresa.licencia_vigente:
        return Response({"error": "Licencia vencida", "licencia_vigente": False}, status=status.HTTP_403_FORBIDDEN)

    nombre_host = request.data.get('nombre_host')
    so = request.data.get('sistema_operativo', 'WINDOWS')
    ip = request.data.get('direccion_ip')

    equipo, _ = Equipo.objects.update_or_create(
        empresa=empresa,
        nombre_host=nombre_host,
        defaults={'sistema_operativo': so, 'direccion_ip': ip, 'agente_activo': True}
    )

    for imp in request.data.get('impresoras', []):
        nombre_cola = imp.get('nombre')
        copias_bn_actual = int(imp.get('copias_bn', 0))
        copias_color_actual = int(imp.get('copias_color', 0))

        imp_existente = Impresora.objects.filter(empresa=empresa, equipo=equipo, nombre_cola=nombre_cola).first()
        if imp_existente:
            if copias_bn_actual > imp_existente.contador_copias_bn and imp_existente.contador_copias_bn > 0:
                nuevas_bn = copias_bn_actual - imp_existente.contador_copias_bn
                RegistroCopia.objects.create(
                    empresa=empresa,
                    impresora=imp_existente,
                    usuario_panel=imp.get('ultimo_usuario_copia') or 'Panel Físico (Multifuncional)',
                    cantidad=nuevas_bn,
                    tipo_copia='BN',
                    costo_total=round(nuevas_bn * float(empresa.costo_pagina_bn), 2)
                )
            if copias_color_actual > imp_existente.contador_copias_color and imp_existente.contador_copias_color > 0:
                nuevas_col = copias_color_actual - imp_existente.contador_copias_color
                RegistroCopia.objects.create(
                    empresa=empresa,
                    impresora=imp_existente,
                    usuario_panel=imp.get('ultimo_usuario_copia') or 'Panel Físico (Multifuncional)',
                    cantidad=nuevas_col,
                    tipo_copia='COLOR',
                    costo_total=round(nuevas_col * float(empresa.costo_pagina_color), 2)
                )

        Impresora.objects.update_or_create(
            empresa=empresa,
            equipo=equipo,
            nombre_cola=nombre_cola,
            defaults={
                'marca': detectar_marca_automatica(nombre_cola),
                'modelo': imp.get('modelo_snmp', ''),
                'puerto_o_ip': imp.get('puerto', ''),
                'ip_impresora': imp.get('ip_impresora'),
                'numero_serie': imp.get('serial', ''),
                'contador_total_fabrica': imp.get('contador_total', 0),
                'contador_copias_bn': copias_bn_actual,
                'contador_copias_color': copias_color_actual,
                'toner_negro': imp.get('toner_negro', -1),
                'toner_cian': imp.get('toner_cian', -1),
                'toner_magenta': imp.get('toner_magenta', -1),
                'toner_amarillo': imp.get('toner_amarillo', -1),
                'es_color': imp.get('es_color', False),
                'estado': imp.get('estado', 'ONLINE')
            }
        )

    impresoras_libres = list(
        Impresora.objects.filter(empresa=empresa, equipo=equipo, control_activo=False)
        .values_list('nombre_cola', flat=True)
    )

    usuarios_cache = []
    for u in PerfilUsuario.objects.filter(empresa=empresa).select_related('departamento'):
        depto = u.departamento
        usuarios_cache.append({
            'usuario_so': u.usuario_sistema_operativo,
            'bloqueado': u.bloqueado_manualmente or (depto.bloqueado if depto else False),
            'requiere_pin': u.requiere_pin_impresion,
            'pin': u.pin_impresion or '',
            'limite_total': u.limite_total_mensual,
            'limite_bn': u.limite_bn_mensual,
            'usado_bn': u.impresiones_bn_mes,
            'limite_color': u.limite_color_mensual,
            'usado_color': u.impresiones_color_mes,
            'depto_limite_bn': depto.limite_bn_mensual if depto else 0,
            'depto_usado_bn': depto.impresiones_bn_mes if depto else 0,
            'depto_limite_color': depto.limite_color_mensual if depto else 0,
            'depto_usado_color': depto.impresiones_color_mes if depto else 0,
        })

    return Response({
        "status": "ok",
        "licencia_vigente": True,
        "reglas_empresa": {
            "licencia_vigente": True,
            "max_paginas_por_trabajo": empresa.max_paginas_por_trabajo,
            "bloquear_color_web_correo": empresa.bloquear_color_web_correo,
            "impresoras_libres": impresoras_libres,
        },
        "usuarios": usuarios_cache
    })


@api_view(['POST'])
def validar_y_registrar_impresion(request):
    token = request.data.get('token_api')
    empresa = Empresa.objects.filter(token_api=token).first()
    if not empresa:
        return Response({"permitir": False, "motivo": "Token inválido"}, status=401)

    if not empresa.licencia_vigente:
        return Response({"permitir": False, "motivo": "Licencia del software vencida. Contacte al administrador."})

    nombre_host = request.data.get('nombre_host')
    nombre_impresora = request.data.get('impresora')
    usuario_so = request.data.get('usuario_so', '').strip()
    documento = request.data.get('documento', 'Sin nombre')
    paginas = int(request.data.get('paginas', 1))
    tipo_impresion = request.data.get('tipo_impresion', 'BN')

    # Limpiar dominio si viene en formato DOMINIO\usuario
    if '\\' in usuario_so:
        usuario_so = usuario_so.split('\\')[-1]

    equipo = Equipo.objects.filter(empresa=empresa, nombre_host=nombre_host).first()
    impresora = Impresora.objects.filter(empresa=empresa, equipo=equipo, nombre_cola=nombre_impresora).first()

    # 1. AUTO-DESCUBRIMIENTO DEL USUARIO (Siempre registrar al usuario aunque luego se bloquee)
    user_django, _ = User.objects.get_or_create(
        username=f"{empresa.id}_{usuario_so}",
        defaults={'is_active': False}
    )
    perfil, _ = PerfilUsuario.objects.get_or_create(
        user=user_django,
        defaults={
            'empresa': empresa,
            'usuario_sistema_operativo': usuario_so,
            'rol': 'EMPLEADO'
        }
    )
    depto = perfil.departamento

    # Si la impresora tiene el control desactivado (ej. RRHH), pasa libre sin restricciones
    if impresora and not impresora.control_activo:
        return Response({"permitir": True, "motivo": "Impresora sin control activo (paso libre)"})

    if impresora and impresora.bloqueada_globalmente:
        RegistroImpresion.objects.create(
            empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
            usuario_so=usuario_so, nombre_documento=documento,
            paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_ADMIN'
        )
        return Response({"permitir": False, "motivo": "Impresora bloqueada"})

    # 2. REGLAS INTELIGENTES DE AHORRO DE LA EMPRESA
    if empresa.max_paginas_por_trabajo > 0 and paginas > empresa.max_paginas_por_trabajo:
        RegistroImpresion.objects.create(
            empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
            usuario_so=usuario_so, nombre_documento=documento,
            paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_REGLA'
        )
        return Response({
            "permitir": False,
            "motivo": f"Regla de Ahorro: El documento ({paginas} págs) supera el máximo permitido ({empresa.max_paginas_por_trabajo} págs)."
        })

    if empresa.bloquear_color_web_correo and tipo_impresion == 'COLOR':
        palabras_clave = [
            'outlook', 'gmail', 'yahoo', 'mail', 'correo',
            'chrome', 'edge', 'firefox', 'brave', 'http://', 'https://', '.html'
        ]
        doc_lower = documento.lower()
        if any(palabra in doc_lower for palabra in palabras_clave):
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_REGLA'
            )
            return Response({
                "permitir": False,
                "motivo": "Regla de Ahorro: Impresión a COLOR bloqueada para correos electrónicos y páginas web."
            })

    # 3. VALIDACIÓN DE BLOQUEO MANUAL DE USUARIO O DEPARTAMENTO
    if perfil.bloqueado_manualmente or (depto and depto.bloqueado):
        RegistroImpresion.objects.create(
            empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
            usuario_so=usuario_so, nombre_documento=documento,
            paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_ADMIN'
        )
        return Response({"permitir": False, "motivo": "Usuario o departamento bloqueado por el administrador"})

    # 4. VALIDACIÓN DE CUOTA POR DEPARTAMENTO
    if depto:
        if tipo_impresion == 'COLOR' and depto.limite_color_mensual > 0 and (depto.impresiones_color_mes + paginas) > depto.limite_color_mensual:
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_DEPTO'
            )
            return Response({"permitir": False, "motivo": f"Cuota COLOR del departamento '{depto.nombre}' excedida."})
        elif tipo_impresion == 'BN' and depto.limite_bn_mensual > 0 and (depto.impresiones_bn_mes + paginas) > depto.limite_bn_mensual:
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_DEPTO'
            )
            return Response({"permitir": False, "motivo": f"Cuota B/N del departamento '{depto.nombre}' excedida."})

    # 5. VALIDACIÓN DE CUOTA GENERAL MIXTA (B/N + COLOR COMBINADOS)
    total_usado_usuario = perfil.impresiones_bn_mes + perfil.impresiones_color_mes
    if perfil.limite_total_mensual > 0 and (total_usado_usuario + paginas) > perfil.limite_total_mensual:
        RegistroImpresion.objects.create(
            empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
            usuario_so=usuario_so, nombre_documento=documento,
            paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_CUOTA'
        )
        return Response({
            "permitir": False,
            "motivo": f"Cuota General Mixta excedida ({total_usado_usuario}/{perfil.limite_total_mensual} págs)."
        })

    # 6. VALIDACIÓN DE CUOTA INDIVIDUAL (B/N Y COLOR SEPARADOS)
    if tipo_impresion == 'COLOR':
        if perfil.limite_color_mensual > 0 and (perfil.impresiones_color_mes + paginas) > perfil.limite_color_mensual:
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_CUOTA'
            )
            return Response({"permitir": False, "motivo": "Cuota mensual a COLOR excedida"})
        perfil.impresiones_color_mes += paginas
        if depto:
            depto.impresiones_color_mes += paginas
        costo = round(paginas * float(empresa.costo_pagina_color), 2)
    else:
        if perfil.limite_bn_mensual > 0 and (perfil.impresiones_bn_mes + paginas) > perfil.limite_bn_mensual:
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_CUOTA'
            )
            return Response({"permitir": False, "motivo": "Cuota mensual B/N excedida"})
        perfil.impresiones_bn_mes += paginas
        if depto:
            depto.impresiones_bn_mes += paginas
        costo = round(paginas * float(empresa.costo_pagina_bn), 2)

    perfil.save()
    if depto:
        depto.save()

    RegistroImpresion.objects.create(
        empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
        usuario_so=usuario_so, nombre_documento=documento,
        paginas=paginas, costo_total=costo, tipo_impresion=tipo_impresion, estado='IMPRESO'
    )

    if perfil.requiere_pin_impresion and perfil.pin_impresion:
        return Response({
            "permitir": True,
            "requiere_pin": True,
            "pin_esperado": perfil.pin_impresion,
            "motivo": "PIN requerido"
        })

    return Response({"permitir": True, "requiere_pin": False, "motivo": "Aprobado"})