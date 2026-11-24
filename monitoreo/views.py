from datetime import datetime
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.template.loader import get_template
from xhtml2pdf import pisa
from .models import Equipo, Impresora, RegistroImpresion, RegistroCopia
from datetime import timedelta
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from empresas.models import Empresa, PerfilUsuario
from .models import Equipo, Impresora, RegistroImpresion


def detectar_marca_automatica(nombre_impresora):
    nombre_upper = nombre_impresora.upper()
    marcas_clave = [
        'HP', 'HEWLETT', 'LEXMARK', 'SHARP', 'RICOH', 'XEROX', 
        'CANON', 'BROTHER', 'EPSON', 'KYOCERA', 'KONICA', 
        'SAMSUNG', 'TOSHIBA', 'OKI', 'PANTUM', 'ZEBRA'
    ]
    for marca in marcas_clave:
        if marca in nombre_upper:
            if marca == 'HEWLETT':
                return 'HP'
            if marca == 'KONICA':
                return 'KONICA_MINOLTA'
            return marca
    return 'OTRA'


# ================= API PARA EL AGENTE =================

@api_view(['POST'])
def sincronizar_equipo(request):
    token = request.data.get('token_api')
    try:
        empresa = Empresa.objects.get(token_api=token)
    except (Empresa.DoesNotExist, ValueError):
        return Response({"error": "Token inválido"}, status=status.HTTP_401_UNAUTHORIZED)

    if not empresa.licencia_vigente:
        return Response({"error": "Licencia vencida o empresa suspendida"}, status=status.HTTP_403_FORBIDDEN)

    nombre_host = request.data.get('nombre_host')
    so = request.data.get('sistema_operativo', 'WINDOWS').upper()
    ip = request.data.get('direccion_ip')

    equipo, _ = Equipo.objects.update_or_create(
        empresa=empresa,
        nombre_host=nombre_host,
        defaults={
            'sistema_operativo': so if so in ['WINDOWS', 'LINUX', 'MACOS'] else 'WINDOWS',
            'direccion_ip': ip,
            'agente_activo': True
        }
    )

    for imp in request.data.get('impresoras', []):
        nombre_cola = imp.get('nombre')
        copias_bn_actual = int(imp.get('copias_bn', 0))
        copias_color_actual = int(imp.get('copias_color', 0))

        imp_existente = Impresora.objects.filter(empresa=empresa, equipo=equipo, nombre_cola=nombre_cola).first()
        if imp_existente:
            # Si el contador subió respecto a la lectura anterior, registramos las copias nuevas
            if copias_bn_actual > imp_existente.contador_copias_bn and imp_existente.contador_copias_bn > 0:
                nuevas_bn = copias_bn_actual - imp_existente.contador_copias_bn
                RegistroCopia.objects.create(
                    empresa=empresa, impresora=imp_existente,
                    usuario_panel=imp.get('ultimo_usuario_copia') or 'Panel Físico (Multifuncional)',
                    cantidad=nuevas_bn, tipo_copia='BN',
                    costo_total=round(nuevas_bn * float(empresa.costo_pagina_bn), 2)
                )
            if copias_color_actual > imp_existente.contador_copias_color and imp_existente.contador_copias_color > 0:
                nuevas_col = copias_color_actual - imp_existente.contador_copias_color
                RegistroCopia.objects.create(
                    empresa=empresa, impresora=imp_existente,
                    usuario_panel=imp.get('ultimo_usuario_copia') or 'Panel Físico (Multifuncional)',
                    cantidad=nuevas_col, tipo_copia='COLOR',
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

    # Preparar datos para la Caché Offline del Agente
    usuarios_cache = []
    for u in PerfilUsuario.objects.filter(empresa=empresa).select_related('departamento'):
        depto = u.departamento
        usuarios_cache.append({
            'usuario_so': u.usuario_sistema_operativo,
            'bloqueado': u.bloqueado_manualmente or (depto.bloqueado if depto else False),
            'requiere_pin': u.requiere_pin_impresion,
            'pin': u.pin_impresion or '',
            'limite_bn': u.limite_bn_mensual,
            'usado_bn': u.impresiones_bn_mes,
            'limite_color': u.limite_color_mensual,
            'usado_color': u.impresiones_color_mes,
            'depto_limite_bn': depto.limite_bn_mensual if depto else 0,
            'depto_usado_bn': depto.impresiones_bn_mes if depto else 0,
            'depto_limite_color': depto.limite_color_mensual if depto else 0,
            'depto_usado_color': depto.impresiones_color_mes if depto else 0,
            'limite_total': u.limite_total_mensual,
        })

    impresoras_libres = list(
        Impresora.objects.filter(empresa=empresa, control_activo=False).values_list('nombre_cola', flat=True)
    )

    return Response({
        "mensaje": "Sincronizado",
        "reglas_empresa": {
            "licencia_vigente": empresa.licencia_vigente,
            "max_paginas_por_trabajo": empresa.max_paginas_por_trabajo,
            "bloquear_color_web_correo": empresa.bloquear_color_web_correo,
            "impresoras_libres": impresoras_libres,  # <-- AGREGA ESTA LÍNEA
        },
        "usuarios": usuarios_cache
    }, status=status.HTTP_200_OK)




@api_view(['POST'])
def validar_y_registrar_impresion(request):
    token = request.data.get('token_api')
    try:
        empresa = Empresa.objects.get(token_api=token)
    except (Empresa.DoesNotExist, ValueError):
        return Response({"permitir": False, "motivo": "Token inválido"}, status=status.HTTP_401_UNAUTHORIZED)

    if not empresa.licencia_vigente:
        return Response({"permitir": False, "motivo": "Licencia del software vencida"}, status=status.HTTP_403_FORBIDDEN)

    nombre_host = request.data.get('nombre_host')
    nombre_impresora = request.data.get('impresora')
    usuario_so = request.data.get('usuario_so')
    documento = request.data.get('documento', 'Documento sin título')
    paginas = int(request.data.get('paginas', 1))
    tipo_impresion = request.data.get('tipo_impresion', 'BN').upper()
    # Calcular costo monetario ($) según el tipo de impresión
    tarifa = empresa.costo_pagina_color if tipo_impresion == 'COLOR' else empresa.costo_pagina_bn
    costo_calculado = round(paginas * float(tarifa), 2)

    equipo = Equipo.objects.filter(empresa=empresa, nombre_host=nombre_host).first()
    impresora = Impresora.objects.filter(empresa=empresa, equipo=equipo, nombre_cola=nombre_impresora).first()

    equipo = Equipo.objects.filter(empresa=empresa, nombre_host=nombre_host).first()
    impresora = Impresora.objects.filter(empresa=empresa, equipo=equipo, nombre_cola=nombre_impresora).first()

    # Si la impresora tiene el control desactivado (ej. RRHH), pasa libre sin restricciones
    if impresora and not impresora.control_activo:
        return Response({"permitir": True, "motivo": "Impresora sin control activo (paso libre)"})

    if impresora and impresora.bloqueada_globalmente:
        RegistroImpresion.objects.create(
            empresa=empresa, equipo=equipo, impresora=impresora,
            usuario_so=usuario_so, nombre_documento=documento,
            paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_ADMIN'
        )
        return Response({"permitir": False, "motivo": "Impresora bloqueada"})

    perfil = PerfilUsuario.objects.filter(empresa=empresa, usuario_sistema_operativo=usuario_so).first()

    # AUTO-DESCUBRIMIENTO: Si el usuario no existe, lo creamos automáticamente
    if not perfil:
        # Limpiar nombre de usuario (ej. si Windows envía "DOMINIO\hreyes", dejamos "hreyes" para el login web)
        username_limpio = usuario_so.split('\\')[-1]
        base_username = f"{username_limpio}_{empresa.id}"
        
        user_django, creado = User.objects.get_or_create(username=base_username)
        if creado:
            user_django.set_unusable_password() # Sin clave web hasta que el admin se la configure
            user_django.save()

        perfil = PerfilUsuario.objects.create(
            user=user_django,
            empresa=empresa,
            rol='EMPLEADO',
            usuario_sistema_operativo=usuario_so,
            limite_bn_mensual=500,    # Cuota inicial por defecto
            limite_color_mensual=100  # Cuota inicial por defecto
        )

    if perfil.bloqueado_manualmente:
        RegistroImpresion.objects.create(
            empresa=empresa, equipo=equipo, impresora=impresora,
            usuario_so=usuario_so, nombre_documento=documento,
            paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_ADMIN'
        )
        return Response({"permitir": False, "motivo": "Usuario bloqueado por el administrador"})
    depto = perfil.departamento

    # 0. REGLAS INTELIGENTES DE AHORRO (PRINT RULES)
    # Regla A: Límite máximo de páginas por un solo documento
    if empresa.max_paginas_por_trabajo > 0 and paginas > empresa.max_paginas_por_trabajo:
        RegistroImpresion.objects.create(
            empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
            usuario_so=usuario_so, nombre_documento=documento,
            paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_REGLA'
        )
        return Response({
            "permitir": False,
            "motivo": f"Regla de Ahorro: El documento ({paginas} págs) supera el máximo permitido de {empresa.max_paginas_por_trabajo} páginas por trabajo."
        })

    # Regla B: Bloquear impresión a COLOR si viene de correo o navegador web
    if empresa.bloquear_color_web_correo and tipo_impresion == 'COLOR':
        doc_lower = documento.lower()
        palabras_web_correo = [
            'outlook', 'gmail', 'yahoo', 'mail', 'correo', 'thunderbird',
            'chrome', 'edge', 'firefox', 'brave', 'safari', 'http://', 'https://', '.html', '.htm'
        ]
        if any(palabra in doc_lower for palabra in palabras_web_correo):
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_REGLA'
            )
            return Response({
                "permitir": False,
                "motivo": "Regla de Ahorro: No se permite imprimir correos o páginas web a COLOR. Cámbielo a Blanco y Negro."
            })

    depto = perfil.departamento

    # 1. VALIDACIÓN NIVEL DEPARTAMENTO (Si el usuario pertenece a uno)
    if depto:
        if depto.bloqueado:
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_ADMIN'
            )
            return Response({"permitir": False, "motivo": f"Departamento '{depto.nombre}' bloqueado"})

        

        if tipo_impresion == 'COLOR':
            if depto.limite_color_mensual > 0 and (depto.impresiones_color_mes + paginas) > depto.limite_color_mensual:
                RegistroImpresion.objects.create(
                    empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                    usuario_so=usuario_so, nombre_documento=documento,
                    paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_DEPTO'
                )
                return Response({"permitir": False, "motivo": f"Cuota COLOR del departamento '{depto.nombre}' excedida"})
        else:
            if depto.limite_bn_mensual > 0 and (depto.impresiones_bn_mes + paginas) > depto.limite_bn_mensual:
                RegistroImpresion.objects.create(
                    empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                    usuario_so=usuario_so, nombre_documento=documento,
                    paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_DEPTO'
                )
                return Response({"permitir": False, "motivo": f"Cuota B/N del departamento '{depto.nombre}' excedida"})

    # 2. VALIDACIÓN NIVEL USUARIO INDIVIDUAL

# 2A. VALIDACIÓN CUOTA GENERAL MIXTA (B/N + COLOR COMBINADOS)
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

    if tipo_impresion == 'COLOR':
        if perfil.limite_color_mensual > 0 and (perfil.impresiones_color_mes + paginas) > perfil.limite_color_mensual:
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_CUOTA'
            )
            return Response({"permitir": False, "motivo": "Cuota individual COLOR excedida"})
    else:
        if perfil.limite_bn_mensual > 0 and (perfil.impresiones_bn_mes + paginas) > perfil.limite_bn_mensual:
            RegistroImpresion.objects.create(
                empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
                usuario_so=usuario_so, nombre_documento=documento,
                paginas=paginas, tipo_impresion=tipo_impresion, estado='BLOQUEADO_CUOTA'
            )
            return Response({"permitir": False, "motivo": "Cuota individual B/N excedida"})

    # 3. DESCONTAR SALDO EN AMBOS NIVELES (Departamento y Usuario)
    if tipo_impresion == 'COLOR':
        perfil.impresiones_color_mes += paginas
        if depto:
            depto.impresiones_color_mes += paginas
    else:
        perfil.impresiones_bn_mes += paginas
        if depto:
            depto.impresiones_bn_mes += paginas

    perfil.save()
    if depto:
        depto.save()

    # 4. VERIFICAR PIN DE SEGURIDAD
    if perfil.requiere_pin_impresion and perfil.pin_impresion:
        RegistroImpresion.objects.create(
            empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
            usuario_so=usuario_so, nombre_documento=documento,
            paginas=paginas, tipo_impresion=tipo_impresion, estado='ESPERANDO_PIN'
        )
        return Response({
            "permitir": True,
            "requiere_pin": True,
            "pin_esperado": perfil.pin_impresion,
            "motivo": "Esperando PIN de seguridad del usuario"
        })

    RegistroImpresion.objects.create(
        empresa=empresa, departamento=depto, equipo=equipo, impresora=impresora,
        usuario_so=usuario_so, nombre_documento=documento,
        paginas=paginas, tipo_impresion=tipo_impresion, estado='IMPRESO'
    )
    return Response({"permitir": True, "motivo": "Aprobado"})  


# ================= HELPER DE LICENCIA Y CONTEXTO =================

def obtener_datos_empresa(user):
    perfil = getattr(user, 'perfil', None)
    if user.is_superuser or (perfil and perfil.rol == 'SUPERADMIN'):
        return None, True, 9999
    if perfil and perfil.empresa:
        emp = perfil.empresa
        return emp, emp.licencia_vigente, emp.dias_restantes
    return None, False, 0


# ================= VISTAS DEL DASHBOARD Y MENÚ =================

def calcular_alertas_predictivas_toner(impresoras_qs):
    """
    Calcula el ritmo diario de impresión de cada máquina (últimos 30 días)
    y estima los días restantes de vida útil de cada cartucho de tóner.
    """
    alertas = []
    hace_30_dias = timezone.now() - timedelta(days=30)

    for imp in impresoras_qs:
        # 1. Calcular páginas impresas en los últimos 30 días en esta impresora
        pags_30d = RegistroImpresion.objects.filter(
            impresora=imp,
            estado='IMPRESO',
            fecha_impresion__gte=hace_30_dias
        ).aggregate(total=Sum('paginas'))['total'] or 0

        # Promedio diario (mínimo 5 págs/día como base conservadora si hay poco historial)
        promedio_diario = round(pags_30d / 30, 1) if pags_30d > 0 else 5.0

        # Rendimiento estimado estándar por cartucho (en páginas)
        rendimiento_cartucho = 3000

        suministros = [
            ('Negro (K)', imp.toner_negro, 'dark'),
            ('Cian (C)', imp.toner_cian, 'info'),
            ('Magenta (M)', imp.toner_magenta, 'danger'),
            ('Amarillo (Y)', imp.toner_amarillo, 'warning'),
        ]

        for nombre_color, porcentaje, badge_color in suministros:
            # Ignorar cartuchos no reportados (-1) o con nivel saludable (> 25%)
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

    # Ordenar primero los más críticos (menor porcentaje)
    alertas.sort(key=lambda x: x['porcentaje'])
    return alertas

@login_required
def dashboard(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    perfil = getattr(request.user, 'perfil', None)

    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.rol == 'EMPLEADO':
        return redirect('portal_empleado')

    if request.user.is_superuser or (perfil and perfil.rol == 'SUPERADMIN'):
        registros = RegistroImpresion.objects.all()
        impresoras = Impresora.objects.all()
        equipos = Equipo.objects.all()
        usuarios_empresa = PerfilUsuario.objects.all()
    else:
        registros = RegistroImpresion.objects.filter(empresa=empresa)
        impresoras = Impresora.objects.filter(empresa=empresa)
        equipos = Equipo.objects.filter(empresa=empresa)
        usuarios_empresa = PerfilUsuario.objects.filter(empresa=empresa)
        if perfil.rol == 'EMPLEADO':
            registros = registros.filter(usuario_so=perfil.usuario_sistema_operativo)

    impresos = registros.filter(estado='IMPRESO')
    total_bn = impresos.filter(tipo_impresion='BN').aggregate(total=Sum('paginas'))['total'] or 0
    total_color = impresos.filter(tipo_impresion='COLOR').aggregate(total=Sum('paginas'))['total'] or 0
    total_bloqueados = registros.exclude(estado='IMPRESO').count()
    costo_total_mes = impresos.aggregate(total=Sum('costo_total'))['total'] or 0
    datos_grafica = impresos.values('impresora__nombre_cola').annotate(total_pags=Sum('paginas')).order_by('-total_pags')[:6]
    alertas_toner = calcular_alertas_predictivas_toner(impresoras)

    return render(request, 'monitoreo/dashboard.html', {
        'seccion_activa': 'dashboard',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'total_paginas_bn': total_bn,
        'total_paginas_color': total_color,
        'total_bloqueados': total_bloqueados,
        'total_impresoras': impresoras.count(),
        'total_equipos': equipos.count(),
        'impresoras_lista': impresoras,
        'usuarios_cuotas': usuarios_empresa[:8],
        'ultimos_registros': registros[:15],
        'etiquetas_impresoras': [d['impresora__nombre_cola'] or 'Otra' for d in datos_grafica],
        'valores_impresoras': [d['total_pags'] for d in datos_grafica],
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
        'impresoras_lista': impresoras,
    })


@login_required
def reportes_vista(request):
    empresa, vigente, dias_restantes = obtener_datos_empresa(request.user)
    if not vigente:
        return render(request, 'monitoreo/licencia_vencida.html', {'empresa': empresa})

    perfil = getattr(request.user, 'perfil', None)
    registros = RegistroImpresion.objects.all() if not empresa else RegistroImpresion.objects.filter(empresa=empresa)
    impresoras = Impresora.objects.all() if not empresa else Impresora.objects.filter(empresa=empresa)

    if perfil and perfil.rol == 'EMPLEADO':
        registros = registros.filter(usuario_so=perfil.usuario_sistema_operativo)

    usuario = request.GET.get('usuario', '')
    impresora_id = request.GET.get('impresora', '')
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')

    if usuario:
        registros = registros.filter(usuario_so__icontains=usuario)
    if impresora_id:
        registros = registros.filter(impresora_id=impresora_id)
    if fecha_inicio:
        registros = registros.filter(fecha_impresion__date__gte=fecha_inicio)
    if fecha_fin:
        registros = registros.filter(fecha_impresion__date__lte=fecha_fin)

    if request.GET.get('exportar') == 'pdf':
        total_bn = registros.filter(estado='IMPRESO', tipo_impresion='BN').aggregate(t=Sum('paginas'))['t'] or 0
        total_color = registros.filter(estado='IMPRESO', tipo_impresion='COLOR').aggregate(t=Sum('paginas'))['t'] or 0
        costo_total = registros.filter(estado='IMPRESO').aggregate(t=Sum('costo_total'))['t'] or 0
        
        template = get_template('monitoreo/reporte_pdf.html')
        html = template.render({
            'registros': registros,
            'empresa': empresa,
            'fecha_generacion': datetime.now(),
            'total_bn': total_bn,
            'total_color': total_color,
            'usuario_filtro': usuario,
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
        })
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="Reporte_Impresiones.pdf"'
        pisa.CreatePDF(html, dest=response)
        return response

    return render(request, 'monitoreo/reportes.html', {
        'seccion_activa': 'reportes',
        'empresa': empresa,
        'dias_restantes': dias_restantes,
        'registros': registros[:100],
        'impresoras_lista': impresoras,
        'usuario': usuario,
        'impresora_id': impresora_id,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
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