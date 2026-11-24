import os
import re
import sys
import json
import time
import socket
import sqlite3
import platform
import configparser
import requests
import tkinter as tk
from tkinter import simpledialog, messagebox
from pysnmp.hlapi import *

# Detectar Sistema Operativo
SISTEMA_OPERATIVO = platform.system().upper()

if SISTEMA_OPERATIVO == 'WINDOWS':
    import win32print
elif SISTEMA_OPERATIVO == 'LINUX':
    import cups

# Ruta real compatible con .py y .exe
if getattr(sys, 'frozen', False):
    RUTA_BASE = os.path.dirname(sys.executable)
else:
    RUTA_BASE = os.path.dirname(os.path.abspath(__file__))

config = configparser.ConfigParser()
config.read(os.path.join(RUTA_BASE, 'config.ini'))

URL_BASE = config['SERVIDOR']['url_base'].rstrip('/')
TOKEN_API = config['SERVIDOR']['token_api']
INTERVALO_SYNC = int(config['SERVIDOR'].get('intervalo_sincronizacion', 60))

NOMBRE_HOST = socket.gethostname()
IP_LOCAL = socket.gethostbyname(NOMBRE_HOST)

# Guardar la base SQLite en una carpeta con permisos de escritura garantizados
if SISTEMA_OPERATIVO == 'WINDOWS':
    DIR_DATOS = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'PrintControl')
else:
    DIR_DATOS = os.path.join(os.path.expanduser('~'), '.printcontrol')

os.makedirs(DIR_DATOS, exist_ok=True)
RUTA_DB_OFFLINE = os.path.join(DIR_DATOS, 'cache_offline.db')

trabajos_procesados = set()


# ================= BASE DE DATOS LOCAL OFFLINE (SQLITE) =================

def inicializar_db_offline():
    conn = sqlite3.connect(RUTA_DB_OFFLINE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS config_cache (
        clave TEXT PRIMARY KEY,
        valor TEXT
    )''')
    # Recrear tabla usuarios_cache para asegurar la columna limite_total
    c.execute('DROP TABLE IF EXISTS usuarios_cache')
    c.execute('''CREATE TABLE usuarios_cache (
        usuario_so TEXT PRIMARY KEY,
        bloqueado INTEGER,
        requiere_pin INTEGER,
        pin TEXT,
        limite_total INTEGER,
        limite_bn INTEGER,
        usado_bn INTEGER,
        limite_color INTEGER,
        usado_color INTEGER,
        depto_limite_bn INTEGER,
        depto_usado_bn INTEGER,
        depto_limite_color INTEGER,
        depto_usado_color INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS cola_pendiente (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload_json TEXT
    )''')
    conn.commit()
    conn.close()


def guardar_cache_offline(reglas_empresa, usuarios):
    conn = sqlite3.connect(RUTA_DB_OFFLINE)
    c = conn.cursor()
    c.execute("REPLACE INTO config_cache (clave, valor) VALUES ('reglas', ?)", (json.dumps(reglas_empresa),))
    c.execute("DELETE FROM usuarios_cache")
    for u in usuarios:
        c.execute('''INSERT INTO usuarios_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            u['usuario_so'], int(u['bloqueado']), int(u['requiere_pin']), u['pin'],
            u.get('limite_total', 0),
            u['limite_bn'], u['usado_bn'], u['limite_color'], u['usado_color'],
            u['depto_limite_bn'], u['depto_usado_bn'], u['depto_limite_color'], u['depto_usado_color']
        ))
    conn.commit()
    conn.close()


def encolar_registro_offline(payload):
    conn = sqlite3.connect(RUTA_DB_OFFLINE)
    c = conn.cursor()
    c.execute("INSERT INTO cola_pendiente (payload_json) VALUES (?)", (json.dumps(payload),))
    conn.commit()
    conn.close()


def reenviar_cola_offline():
    """Sube al servidor los trabajos procesados mientras no había conexión."""
    conn = sqlite3.connect(RUTA_DB_OFFLINE)
    c = conn.cursor()
    c.execute("SELECT id, payload_json FROM cola_pendiente ORDER BY id ASC")
    pendientes = c.fetchall()
    for reg_id, payload_str in pendientes:
        try:
            resp = requests.post(f"{URL_BASE}/api/validar-impresion/", json=json.loads(payload_str), timeout=4)
            if resp.status_code in [200, 403]:
                c.execute("DELETE FROM cola_pendiente WHERE id = ?", (reg_id,))
                conn.commit()
        except Exception:
            break
    conn.close()


def impresora_tiene_control_activo(nombre_imp):
    """Verifica en la caché local si la impresora tiene el monitoreo activado."""
    try:
        conn = sqlite3.connect(RUTA_DB_OFFLINE)
        c = conn.cursor()
        c.execute("SELECT valor FROM config_cache WHERE clave = 'reglas'")
        fila = c.fetchone()
        conn.close()
        if fila:
            reglas = json.loads(fila[0])
            if nombre_imp in reglas.get('impresoras_libres', []):
                return False
    except Exception:
        pass
    return True


def validar_en_modo_offline(usuario_so, documento, paginas, tipo_impresion):
    """Evalúa reglas, cuotas (mixta e individuales) y PIN localmente cuando el servidor no responde."""
    conn = sqlite3.connect(RUTA_DB_OFFLINE)
    c = conn.cursor()

    c.execute("SELECT valor FROM config_cache WHERE clave = 'reglas'")
    fila_reglas = c.fetchone()
    reglas = json.loads(fila_reglas[0]) if fila_reglas else {}

    if reglas and not reglas.get('licencia_vigente', True):
        conn.close()
        return {"permitir": False, "motivo": "Licencia vencida (Modo Offline)"}

    max_pags = reglas.get('max_paginas_por_trabajo', 0)
    if max_pags > 0 and paginas > max_pags:
        conn.close()
        return {"permitir": False, "motivo": f"Regla de Ahorro (Offline): Máximo {max_pags} páginas por trabajo."}

    if reglas.get('bloquear_color_web_correo') and tipo_impresion == 'COLOR':
        palabras = ['outlook', 'gmail', 'yahoo', 'mail', 'correo', 'chrome', 'edge', 'firefox', 'http://', 'https://', '.html']
        if any(p in documento.lower() for p in palabras):
            conn.close()
            return {"permitir": False, "motivo": "Regla de Ahorro (Offline): Bloqueado color en correo/web."}

    c.execute("SELECT * FROM usuarios_cache WHERE usuario_so = ?", (usuario_so,))
    u = c.fetchone()
    if not u:
        conn.close()
        return {"permitir": True, "motivo": "Aprobado (Usuario nuevo en modo offline)"}

    _, bloqueado, req_pin, pin, lim_total, lim_bn, uso_bn, lim_col, uso_col, d_lim_bn, d_uso_bn, d_lim_col, d_uso_col = u

    if bloqueado:
        conn.close()
        return {"permitir": False, "motivo": "Usuario o departamento bloqueado (Modo Offline)"}

    # Validar cuota general mixta (B/N + Color)
    if lim_total > 0 and (uso_bn + uso_col + paginas) > lim_total:
        conn.close()
        return {"permitir": False, "motivo": "Cuota General Mixta excedida (Modo Offline)"}

    if tipo_impresion == 'COLOR':
        if (d_lim_col > 0 and (d_uso_col + paginas) > d_lim_col) or (lim_col > 0 and (uso_col + paginas) > lim_col):
            conn.close()
            return {"permitir": False, "motivo": "Cuota COLOR excedida (Modo Offline)"}
        c.execute("UPDATE usuarios_cache SET usado_color = usado_color + ?, depto_usado_color = depto_usado_color + ? WHERE usuario_so = ?", (paginas, paginas, usuario_so))
    else:
        if (d_lim_bn > 0 and (d_uso_bn + paginas) > d_lim_bn) or (lim_bn > 0 and (uso_bn + paginas) > lim_bn):
            conn.close()
            return {"permitir": False, "motivo": "Cuota B/N excedida (Modo Offline)"}
        c.execute("UPDATE usuarios_cache SET usado_bn = usado_bn + ?, depto_usado_bn = depto_usado_bn + ? WHERE usuario_so = ?", (paginas, paginas, usuario_so))

    conn.commit()
    conn.close()

    if req_pin and pin:
        return {"permitir": True, "requiere_pin": True, "pin_esperado": pin, "motivo": "PIN Offline"}

    return {"permitir": True, "motivo": "Aprobado en Modo Offline"}


# ================= SNMP (TÓNER Y CONTADORES DE COPIAS) =================

def extraer_ip_de_puerto(puerto_texto):
    match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', str(puerto_texto))
    return match.group(1) if match else None


def consultar_snmp_impresora(ip):
    datos = {
        'modelo_snmp': '', 'serial': '', 'contador_total': 0,
        'copias_bn': 0, 'copias_color': 0,
        'toner_negro': -1, 'toner_cian': -1, 'toner_magenta': -1, 'toner_amarillo': -1
    }
    if not ip:
        return datos

    oids = {
        'modelo': '1.3.6.1.2.1.25.3.2.1.3.1',
        'serial': '1.3.6.1.2.1.43.5.1.1.17.1',
        'contador': '1.3.6.1.2.1.43.10.2.1.4.1.1',
        'copias_bn': '1.3.6.1.2.1.43.10.2.1.4.1.2',
        'copias_color': '1.3.6.1.2.1.43.10.2.1.4.1.3',
        'max_1': '1.3.6.1.2.1.43.11.1.1.8.1.1', 'act_1': '1.3.6.1.2.1.43.11.1.1.9.1.1',
        'max_2': '1.3.6.1.2.1.43.11.1.1.8.1.2', 'act_2': '1.3.6.1.2.1.43.11.1.1.9.1.2',
        'max_3': '1.3.6.1.2.1.43.11.1.1.8.1.3', 'act_3': '1.3.6.1.2.1.43.11.1.1.9.1.3',
        'max_4': '1.3.6.1.2.1.43.11.1.1.8.1.4', 'act_4': '1.3.6.1.2.1.43.11.1.1.9.1.4',
    }

    resultados = {}
    for clave, oid in oids.items():
        try:
            iterator = getCmd(
                SnmpEngine(), CommunityData('public', mpModel=0),
                UdpTransportTarget((ip, 161), timeout=1.0, retries=0),
                ContextData(), ObjectType(ObjectIdentity(oid))
            )
            errorIndication, errorStatus, _, varBinds = next(iterator)
            if not errorIndication and not errorStatus:
                resultados[clave] = str(varBinds[0][1])
        except Exception:
            pass

    datos['modelo_snmp'] = resultados.get('modelo', '')[:95]
    datos['serial'] = resultados.get('serial', '')[:95]
    if resultados.get('contador', '').isdigit():
        datos['contador_total'] = int(resultados['contador'])
    if resultados.get('copias_bn', '').isdigit():
        datos['copias_bn'] = int(resultados['copias_bn'])
    if resultados.get('copias_color', '').isdigit():
        datos['copias_color'] = int(resultados['copias_color'])

    def calc_pct(clave_act, clave_max):
        try:
            act = int(resultados.get(clave_act, -1))
            mx = int(resultados.get(clave_max, -1))
            if act >= 0 and mx > 0:
                return min(100, int((act / mx) * 100))
        except Exception:
            pass
        return -1

    datos['toner_negro'] = calc_pct('act_1', 'max_1')
    datos['toner_cian'] = calc_pct('act_2', 'max_2')
    datos['toner_magenta'] = calc_pct('act_3', 'max_3')
    datos['toner_amarillo'] = calc_pct('act_4', 'max_4')
    return datos


# ================= VENTANAS DE USUARIO =================

def solicitar_pin_en_pantalla(documento, pin_esperado):
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    for intento in range(3):
        pin_ingresado = simpledialog.askstring(
            "PrintControl - Impresión Segura",
            f"Documento: {documento}\nIngrese su PIN de impresión (Intento {intento + 1}/3):",
            show='*', parent=root
        )
        if pin_ingresado is None:
            root.destroy()
            return False
        if pin_ingresado.strip() == str(pin_esperado).strip():
            root.destroy()
            return True
        messagebox.showerror("PIN Incorrecto", "La contraseña de impresión no es válida.", parent=root)
    root.destroy()
    return False


def mostrar_aviso_bloqueo(documento, motivo):
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showwarning("PrintControl - Impresión Detenida", f"Documento: {documento}\n\n{motivo}", parent=root)
        root.destroy()
    except Exception:
        pass


# ================= DETECCIÓN Y VIGILANCIA DE COLAS =================

def obtener_impresoras_windows():
    impresoras = []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for _, _, nombre, _ in win32print.EnumPrinters(flags):
        try:
            handle = win32print.OpenPrinter(nombre)
            info = win32print.GetPrinter(handle, 2)
            win32print.ClosePrinter(handle)

            puerto = info.get('pPortName', 'Desconocido')
            estado = 'ONLINE' if info.get('Status', 0) == 0 else 'ERROR'
            devmode = info.get('pDevMode')
            es_color = True if (devmode and getattr(devmode, 'Color', 1) == 2) else False

            ip_imp = extraer_ip_de_puerto(puerto)
            snmp_info = consultar_snmp_impresora(ip_imp)

            impresoras.append({
                'nombre': nombre, 'puerto': puerto, 'ip_impresora': ip_imp,
                'es_color': es_color, 'estado': estado, **snmp_info
            })
        except Exception:
            pass
    return impresoras


def obtener_impresoras_linux():
    impresoras = []
    try:
        conn = cups.Connection()
        for nombre, attrs in conn.getPrinters().items():
            estado = 'ONLINE' if attrs.get('printer-state', 3) in [3, 4] else 'ERROR'
            es_color = attrs.get('color-supported', False)
            puerto = attrs.get('device-uri', 'CUPS')
            ip_imp = extraer_ip_de_puerto(puerto)
            snmp_info = consultar_snmp_impresora(ip_imp)

            impresoras.append({
                'nombre': nombre, 'puerto': puerto, 'ip_impresora': ip_imp,
                'es_color': es_color, 'estado': estado, **snmp_info
            })
    except Exception:
        pass
    return impresoras


def sincronizar_con_servidor():
    lista_impresoras = obtener_impresoras_windows() if SISTEMA_OPERATIVO == 'WINDOWS' else obtener_impresoras_linux()
    payload = {
        'token_api': TOKEN_API,
        'nombre_host': NOMBRE_HOST,
        'sistema_operativo': SISTEMA_OPERATIVO,
        'direccion_ip': IP_LOCAL,
        'impresoras': lista_impresoras
    }

    try:
        resp = requests.post(f"{URL_BASE}/api/sincronizar/", json=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            guardar_cache_offline(data.get('reglas_empresa', {}), data.get('usuarios', []))
            reenviar_cola_offline()
            print(f"[✓] Sincronizado y Caché Offline actualizada ({len(lista_impresoras)} impresoras)")
    except Exception:
        print("[!] Servidor sin conexión: operando en Modo Offline con caché local.")


def consultar_permiso_impresion(impresora, usuario_so, documento, paginas, tipo_impresion):
    payload = {
        'token_api': TOKEN_API,
        'nombre_host': NOMBRE_HOST,
        'impresora': impresora,
        'usuario_so': usuario_so,
        'documento': documento,
        'paginas': paginas,
        'tipo_impresion': tipo_impresion
    }
    try:
        resp = requests.post(f"{URL_BASE}/api/validar-impresion/", json=payload, timeout=4)
        return resp.json()
    except Exception:
        resultado_offline = validar_en_modo_offline(usuario_so, documento, paginas, tipo_impresion)
        encolar_registro_offline(payload)
        return resultado_offline


def vigilar_cola_windows():
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for _, _, nombre_imp, _ in win32print.EnumPrinters(flags):
        if not impresora_tiene_control_activo(nombre_imp):
            continue

        try:
            handle = win32print.OpenPrinter(nombre_imp)
            trabajos = win32print.EnumJobs(handle, 0, -1, 2)

            for job in trabajos:
                job_id = f"{nombre_imp}_{job['JobId']}"
                if job_id in trabajos_procesados:
                    continue

                win32print.SetJob(handle, job['JobId'], 0, None, win32print.JOB_CONTROL_PAUSE)

                usuario_so = job.get('pUserName', 'desconocido')
                documento = job.get('pDocument', 'Sin nombre')
                paginas = job.get('TotalPages', 1) or 1
                devmode = job.get('pDevMode')
                tipo_impresion = 'COLOR' if (devmode and getattr(devmode, 'Color', 1) == 2) else 'BN'

                resp_json = consultar_permiso_impresion(nombre_imp, usuario_so, documento, paginas, tipo_impresion)
                permitir = resp_json.get('permitir', False)
                requiere_pin = resp_json.get('requiere_pin', False)
                motivo = resp_json.get('motivo', '')

                if permitir and requiere_pin:
                    permitir = solicitar_pin_en_pantalla(documento, resp_json.get('pin_esperado'))
                    if not permitir:
                        motivo = "PIN incorrecto o cancelado por el usuario."

                if permitir:
                    win32print.SetJob(handle, job['JobId'], 0, None, win32print.JOB_CONTROL_RESUME)
                else:
                    win32print.SetJob(handle, job['JobId'], 0, None, win32print.JOB_CONTROL_DELETE)
                    mostrar_aviso_bloqueo(documento, motivo)

                trabajos_procesados.add(job_id)

            win32print.ClosePrinter(handle)
        except Exception:
            pass


def vigilar_cola_linux():
    try:
        conn = cups.Connection()
        for job_id_num, info in conn.getJobs(which_jobs='not-completed').items():
            job_id = f"CUPS_{job_id_num}"
            if job_id in trabajos_procesados:
                continue

            attrs = conn.getJobAttributes(job_id_num)
            nombre_imp = attrs.get('printer-uri', '').split('/')[-1]
            if not impresora_tiene_control_activo(nombre_imp):
                continue

            conn.holdJob(job_id_num)

            usuario_so = attrs.get('job-originating-user-name', 'desconocido')
            documento = attrs.get('job-name', 'Sin nombre')
            paginas = attrs.get('job-media-sheets', 1) or 1
            color_mode = str(attrs.get('print-color-mode', 'monochrome')).lower()
            tipo_impresion = 'COLOR' if 'color' in color_mode else 'BN'

            resp_json = consultar_permiso_impresion(nombre_imp, usuario_so, documento, paginas, tipo_impresion)
            permitir = resp_json.get('permitir', False)
            requiere_pin = resp_json.get('requiere_pin', False)
            motivo = resp_json.get('motivo', '')

            if permitir and requiere_pin:
                permitir = solicitar_pin_en_pantalla(documento, resp_json.get('pin_esperado'))
                if not permitir:
                    motivo = "PIN incorrecto o cancelado por el usuario."

            if permitir:
                conn.releaseJob(job_id_num)
            else:
                conn.cancelJob(job_id_num)
                mostrar_aviso_bloqueo(documento, motivo)

            trabajos_procesados.add(job_id)
    except Exception:
        pass


if __name__ == '__main__':
    inicializar_db_offline()
    print(f"=== Iniciando Agente PrintControl con Caché Offline en {NOMBRE_HOST} ({SISTEMA_OPERATIVO}) ===")
    ultimo_sync = 0

    while True:
        ahora = time.time()
        if ahora - ultimo_sync >= INTERVALO_SYNC:
            sincronizar_con_servidor()
            ultimo_sync = ahora

        if SISTEMA_OPERATIVO == 'WINDOWS':
            vigilar_cola_windows()
        elif SISTEMA_OPERATIVO == 'LINUX':
            vigilar_cola_linux()

        time.sleep(0.5)