import os
import re
import sys
import json
import time
import socket
import logging
import sqlite3
import platform
import configparser
import requests
import tkinter as tk
from tkinter import simpledialog, messagebox
from pysnmp.hlapi import *

SISTEMA_OPERATIVO = platform.system().upper()

if SISTEMA_OPERATIVO == 'WINDOWS':
    import win32print
elif SISTEMA_OPERATIVO == 'LINUX':
    import cups

# Ruta base compatible con .py y .exe
if getattr(sys, 'frozen', False):
    RUTA_BASE = os.path.dirname(sys.executable)
else:
    RUTA_BASE = os.path.dirname(os.path.abspath(__file__))

# Carpeta de datos con permisos de escritura garantizados
if SISTEMA_OPERATIVO == 'WINDOWS':
    DIR_DATOS = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'PrintControl')
else:
    DIR_DATOS = os.path.join(os.path.expanduser('~'), '.printcontrol')

os.makedirs(DIR_DATOS, exist_ok=True)
RUTA_DB_OFFLINE = os.path.join(DIR_DATOS, 'cache_offline.db')
RUTA_LOG = os.path.join(DIR_DATOS, 'agente.log')

logging.basicConfig(
    filename=RUTA_LOG,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

config = configparser.ConfigParser()
ruta_ini = os.path.join(RUTA_BASE, 'config.ini')
if not os.path.exists(ruta_ini):
    logging.error(f"No se encontró config.ini en {ruta_ini}")

config.read(ruta_ini)
URL_BASE = config.get('SERVIDOR', 'url_base', fallback='http://127.0.0.1:8000').strip().rstrip('/')
if not URL_BASE.startswith('http'):
    URL_BASE = f"http://{URL_BASE}"
TOKEN_API = config.get('SERVIDOR', 'token_api', fallback='').strip()
INTERVALO_SYNC = int(config.get('SERVIDOR', 'intervalo_sincronizacion', fallback='30'))

NOMBRE_HOST = socket.gethostname()
try:
    IP_LOCAL = socket.gethostbyname(NOMBRE_HOST)
except Exception:
    IP_LOCAL = '127.0.0.1'

trabajos_procesados = set()


# ================= BASE DE DATOS LOCAL OFFLINE (SQLITE) =================

def inicializar_db_offline():
    conn = sqlite3.connect(RUTA_DB_OFFLINE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS config_cache (
        clave TEXT PRIMARY KEY,
        valor TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios_cache (
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
    # Verificar si falta la columna limite_total en instalaciones previas
    c.execute("PRAGMA table_info(usuarios_cache)")
    columnas = [col[1] for col in c.fetchall()]
    if 'limite_total' not in columnas:
        c.execute("ALTER TABLE usuarios_cache ADD COLUMN limite_total INTEGER DEFAULT 0")

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
        c.execute('''INSERT INTO usuarios_cache (
            usuario_so, bloqueado, requiere_pin, pin, limite_total,
            limite_bn, usado_bn, limite_color, usado_color,
            depto_limite_bn, depto_usado_bn, depto_limite_color, depto_usado_color
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
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
    conn = sqlite3.connect(RUTA_DB_OFFLINE)
    c = conn.cursor()
    c.execute("SELECT id, payload_json FROM cola_pendiente ORDER BY id ASC")
    pendientes = c.fetchall()
    for reg_id, payload_str in pendientes:
        try:
            resp = requests.post(f"{URL_BASE}/api/validar-impresion/", json=json.loads(payload_str), timeout=4)
            if resp.status_code in [200, 401, 403]:
                c.execute("DELETE FROM cola_pendiente WHERE id = ?", (reg_id,))
                conn.commit()
        except Exception:
            break
    conn.close()


def impresora_tiene_control_activo(nombre_imp):
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

    c.execute("""SELECT bloqueado, requiere_pin, pin, limite_total,
                        limite_bn, usado_bn, limite_color, usado_color,
                        depto_limite_bn, depto_usado_bn, depto_limite_color, depto_usado_color
                 FROM usuarios_cache WHERE usuario_so = ?""", (usuario_so,))
    u = c.fetchone()
    if not u:
        conn.close()
        return {"permitir": True, "motivo": "Aprobado (Usuario nuevo en modo offline)"}

    bloqueado, req_pin, pin, lim_total, lim_bn, uso_bn, lim_col, uso_col, d_lim_bn, d_uso_bn, d_lim_col, d_uso_col = u

    if bloqueado:
        conn.close()
        return {"permitir": False, "motivo": "Usuario o departamento bloqueado (Modo Offline)"}

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
                UdpTransportTarget((ip, 161), timeout=0.8, retries=0),
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
        except Exception as e:
            logging.warning(f"Error leyendo impresora '{nombre}': {e}")
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
    except Exception as e:
        logging.warning(f"Error leyendo CUPS: {e}")
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
            msg = f"Sincronizado OK ({len(lista_impresoras)} impresoras, {len(data.get('usuarios', []))} usuarios en caché)"
            print(f"[✓] {msg}")
            logging.info(msg)
        else:
            msg = f"Error HTTP {resp.status_code} al sincronizar: {resp.text[:150]}"
            print(f"[!] {msg}")
            logging.error(msg)
    except Exception as e:
        msg = f"Servidor sin conexión ({URL_BASE}): {e}"
        print(f"[!] {msg}")
        logging.warning(msg)


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
    except Exception as e:
        logging.warning(f"Validando offline por error de red: {e}")
        resultado_offline = validar_en_modo_offline(usuario_so, documento, paginas, tipo_impresion)
        encolar_registro_offline(payload)
        return resultado_offline


def vigilar_cola_windows():
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for _, _, nombre_imp, _ in win32print.EnumPrinters(flags):
        if not impresora_tiene_control_activo(nombre_imp):
            continue

        handle = None
        try:
            try:
                handle = win32print.OpenPrinter(nombre_imp, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
            except Exception:
                handle = win32print.OpenPrinter(nombre_imp)

            trabajos = win32print.EnumJobs(handle, 0, -1, 2)
            for job in trabajos:
                job_id = f"{nombre_imp}_{job['JobId']}"
                if job_id in trabajos_procesados:
                    continue

                # 1. Pausar de inmediato antes de que salga a la impresora
                try:
                    win32print.SetJob(handle, job['JobId'], 0, None, win32print.JOB_CONTROL_PAUSE)
                except Exception as e_pause:
                    logging.error(f"No se pudo pausar trabajo {job_id} (¿falta ejecutar como Admin?): {e_pause}")
                    trabajos_procesados.add(job_id)
                    continue

                # Esperar hasta que Windows termine de recibir todas las páginas del archivo (Spooling)
                job_actual = job
                for _ in range(15):  # Máximo 1.5 segundos de espera
                    try:
                        job_actual = win32print.GetJob(handle, job['JobId'], 2)
                        estado_spool = job_actual.get('Status', 0)
                        pags_detectadas = job_actual.get('TotalPages', 0) or 0
                        # Si ya terminó de hacer spooling (bit 0x00000008 = JOB_STATUS_SPOOLING) y tiene páginas
                        if not (estado_spool & 0x00000008) and pags_detectadas > 0:
                            break
                    except Exception:
                        break
                    time.sleep(0.1)

                paginas_doc = job_actual.get('TotalPages', 1) or 1
                devmode = job_actual.get('pDevMode') or job.get('pDevMode')
                copias = getattr(devmode, 'Copies', 1) if devmode else 1
                if not copias or copias < 1:
                    copias = 1

                paginas = paginas_doc * copias

                usuario_raw = job_actual.get('pUserName') or job.get('pUserName') or 'desconocido'
                usuario_so = usuario_raw.split('\\')[-1].strip()
                documento = job_actual.get('pDocument') or job.get('pDocument') or 'Sin nombre'
                tipo_impresion = 'COLOR' if (devmode and getattr(devmode, 'Color', 1) == 2) else 'BN'

                logging.info(f"Interceptado: imp='{nombre_imp}' user='{usuario_so}' doc='{documento}' pags={paginas} tipo={tipo_impresion}")

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
                    logging.info(f"Aprobado y reanudado: {job_id}")
                else:
                    win32print.SetJob(handle, job['JobId'], 0, None, win32print.JOB_CONTROL_DELETE)
                    logging.info(f"Bloqueado y eliminado: {job_id} -> {motivo}")
                    mostrar_aviso_bloqueo(documento, motivo)

                trabajos_procesados.add(job_id)

        except Exception as e:
            logging.error(f"Error vigilando cola '{nombre_imp}': {e}")
        finally:
            if handle:
                try:
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
    except Exception as e:
        logging.error(f"Error vigilando CUPS: {e}")


if __name__ == '__main__':
    inicializar_db_offline()
    logging.info(f"Iniciando Agente en {NOMBRE_HOST} -> Servidor: {URL_BASE}")
    print(f"=== Iniciando Agente PrintControl en {NOMBRE_HOST} ({SISTEMA_OPERATIVO}) ===")
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

        time.sleep(0.05)