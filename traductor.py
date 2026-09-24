# -*- coding: utf-8 -*-
"""
Traducción de guiones con un modelo local (llama.cpp), respetando el perfil
de estilo del traductor y su glosario.

Cómo trabaja:
- Traduce por bloques de líneas, dándole al modelo las últimas líneas ya
  traducidas y las siguientes como contexto, para que el tono sea coherente.
- Solo manda del glosario los términos y personajes que aparecen en el bloque.
- La respuesta está obligada a ser JSON con una traducción por línea (gramática
  de llama.cpp), así no se pierden ni se juntan líneas; si aun así falta alguna,
  se reintenta línea por línea.
- La columna PERSONAJE no pasa por el modelo: se cambia con el glosario.
- Al final revisa que los términos del glosario estén en la traducción, y marca
  para revisar las líneas donde no.
"""

import json
import re
import unicodedata

import motor_llm
import modelos_traduccion

IDIOMAS = {"en": "inglés", "es": "español", "fr": "francés", "ja": "japonés", "pt": "portugués",
           "it": "italiano", "de": "alemán", "ko": "coreano", "zh": "chino", "ar": "árabe", "auto": "el idioma original"}

LINEAS_POR_BLOQUE = 16
CONTEXTO_PREVIO = 6
CONTEXTO_SIGUIENTE = 3

PATRON_SOLO_ACOTACION = re.compile(r"^\s*[\(\[][^\)\]]*[\)\]]\s*$")
PATRON_PARENTESIS = re.compile(r"\([^)]*\)")
PATRON_MARCA_VOZ = re.compile(r"\s*\((?:off|o\.s\.|v\.o\.|vo|os)\)\s*$", re.IGNORECASE)


def _normalizar(texto):
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii").lower().strip()


def _aparece(termino, texto):
    t = _normalizar(termino)
    return bool(t) and re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", _normalizar(texto)) is not None


class Glosario:
    def __init__(self, glosario):
        self.personajes = glosario.get("personajes") or []
        self.terminos = glosario.get("terminos") or []
        self._etiquetas = {}
        for p in self.personajes:
            # El nombre de doblaje también cuenta: "FRANK" → "FRANK" ya está en el glosario
            for nombre in [p["doblaje"], p["original"]] + list(p.get("variantes") or []):
                self._etiquetas[_normalizar(nombre)] = p["doblaje"]

    def etiqueta(self, personaje):
        """PERSONAJE traducido con el glosario; cada nombre de una lista "A, B" por separado."""
        partes = [x.strip() for x in (personaje or "").split(",")]
        traducidas, faltan = [], []
        for parte in partes:
            if not parte:
                continue
            # "ASSAN (OFF)" se busca como "ASSAN" y la marca se conserva
            marca = PATRON_MARCA_VOZ.search(parte)
            destino = self._etiquetas.get(_normalizar(PATRON_MARCA_VOZ.sub("", parte)))
            if destino:
                traducidas.append(destino + (marca.group(0).upper() if marca else ""))
            else:
                traducidas.append(parte)
                faltan.append(parte)
        return ", ".join(traducidas), faltan

    def para_bloque(self, textos):
        """Entradas del glosario que aparecen en el bloque: [(original, destino, nota)]."""
        texto = "\n".join(textos)
        entradas = []
        for p in self.personajes:
            if (p.get("tipo") or "personaje") == "etiqueta":
                continue  # las etiquetas no se reemplazan en el diálogo
            destino = p.get("en_dialogo") or p["doblaje"].title()
            for nombre in [p["original"]] + list(p.get("variantes") or []):
                if _aparece(nombre, texto):
                    entradas.append((nombre, destino, "nombre de personaje"))
                    break
        for t in self.terminos:
            if _aparece(t["original"], texto):
                entradas.append((t["original"], t["doblaje"], t.get("notas") or ""))
        return entradas


def _mensaje_sistema(perfil):
    origen = IDIOMAS.get(perfil.get("idioma_origen") or "en", perfil.get("idioma_origen"))
    variante = perfil.get("variante") or "español latino neutro"
    reglas = (perfil.get("instrucciones") or "").strip()
    return (
        f"Eres traductor profesional de doblaje. Traduces diálogos del {origen} al {variante}.\n\n"
        "Reglas generales:\n"
        "- Traduce el sentido y el tono, no palabra por palabra: frases naturales para decirse en voz alta.\n"
        "- Mantén una longitud parecida a la del original (la línea se dobla sobre la boca del personaje).\n"
        "- No agregues ni quites información, no expliques y no añadas notas.\n"
        "- Traduce las acotaciones entre paréntesis o corchetes y déjalas en su lugar.\n"
        "- Cada línea se traduce por separado: no juntes ni dividas líneas.\n"
        "- Usa exactamente las formas del glosario cuando aparezca un término.\n"
        "- Escribe con mayúsculas y minúsculas normales, aunque las reglas pidan entregar en MAYÚSCULAS: "
        "eso lo aplica la app al final.\n"
        + (f"\nReglas del traductor (mandan sobre las generales):\n{reglas}\n" if reglas else "")
    )


def _mensaje_bloque(bloque, previas, siguientes, glosario):
    partes = []
    entradas = glosario.para_bloque([f["dialogo"] for f in bloque])
    if entradas:
        partes.append("Glosario obligatorio:\n" + "\n".join(
            f"- {o} → {d}" + (f" ({n})" if n else "") for o, d, n in entradas))
    if previas:
        partes.append("Contexto anterior, ya traducido (no lo repitas):\n" + json.dumps(
            [{"personaje": f["personaje"], "texto": f["dialogo"], "traduccion": f["traduccion"]} for f in previas],
            ensure_ascii=False))
    lineas = [{"id": i + 1, "personaje": f["personaje"] or "?", "texto": f["dialogo"]} for i, f in enumerate(bloque)]
    partes.append(f"Líneas a traducir ({len(bloque)}):\n" + json.dumps(lineas, ensure_ascii=False, indent=0))
    if siguientes:
        partes.append("Contexto siguiente (NO lo traduzcas):\n" + json.dumps(
            [{"personaje": f["personaje"], "texto": f["dialogo"]} for f in siguientes], ensure_ascii=False))
    partes.append(f'Responde solo con JSON: {{"traducciones": [{{"id": 1, "texto": "..."}}, …]}} '
                  f"con exactamente {len(bloque)} elementos, uno por línea y en el mismo orden. "
                  "En \"texto\" va solo el diálogo traducido, sin el nombre del personaje.")
    return "\n\n".join(partes)


def _esquema(n):
    return {
        "type": "object",
        "properties": {"traducciones": {
            "type": "array", "minItems": n, "maxItems": n,
            "items": {"type": "object", "properties": {"id": {"type": "integer"}, "texto": {"type": "string"}},
                      "required": ["id", "texto"]},
        }},
        "required": ["traducciones"],
    }


def _traducir_bloque(servidor, sistema, bloque, previas, siguientes, glosario):
    mensajes = [{"role": "system", "content": sistema},
                {"role": "user", "content": _mensaje_bloque(bloque, previas, siguientes, glosario)}]
    texto, _ = servidor.chat(mensajes, esquema=_esquema(len(bloque)), max_tokens=120 * len(bloque) + 200)
    datos = json.loads(texto)
    por_id = {int(x["id"]): (x.get("texto") or "").strip() for x in datos.get("traducciones", [])}
    return [_sin_nombre(por_id.get(i + 1, ""), f["personaje"]) for i, f in enumerate(bloque)]


def _sin_nombre(traduccion, personaje):
    """Quita el nombre del personaje si el modelo lo copió al inicio ("MAX | Amigo…", "[MAX] Amigo…")."""
    if personaje:
        nombre = re.escape(personaje.strip())
        traduccion = re.sub(rf"^\s*\[?{nombre}\]?\s*[|:\-–]\s*", "", traduccion, flags=re.IGNORECASE)
    return traduccion.strip()


def _pos_proceso(traduccion, perfil):
    acotacion = (perfil.get("acotacion") or "").strip()
    if acotacion:
        traduccion = PATRON_PARENTESIS.sub(acotacion, traduccion)
    traduccion = re.sub(r"\s+", " ", traduccion).strip()
    if perfil.get("mayusculas"):
        traduccion = traduccion.upper()
    return traduccion


def traducir(filas, perfil, id_modelo, en_gpu, progreso=None, cancelado=lambda: False, log=None):
    """
    filas: [{"timecode", "personaje", "dialogo"}]. Devuelve (filas, sin_glosario): las filas con
    "original", "dialogo" traducido, "personaje" adaptado, "revisar" y "avisos", y un
    diccionario {personaje: líneas} de los personajes que no están en el glosario.
    """
    progreso = progreso or (lambda *a: None)
    log = log or (lambda *a: None)
    glosario = Glosario(perfil.get("glosario") or {})
    sistema = _mensaje_sistema(perfil)

    log(f"Modelo: {modelos_traduccion.POR_ID[id_modelo]['nombre']} en {'GPU' if en_gpu else 'procesador'}")
    motor_llm.SERVIDOR.iniciar(modelos_traduccion.ruta(id_modelo), en_gpu, log=log)

    resultado = []
    sin_glosario = {}  # nombre → cantidad de líneas (se informa una vez, no en cada fila)
    for f in filas:
        etiqueta, faltan = glosario.etiqueta(f.get("personaje", ""))
        if glosario.personajes:
            for nombre in faltan:
                sin_glosario[nombre] = sin_glosario.get(nombre, 0) + 1
        resultado.append({"timecode": f.get("timecode", ""), "personaje": etiqueta, "personaje_original": f.get("personaje", ""),
                          "original": f.get("dialogo", ""), "dialogo": "", "traduccion": "",
                          "revisar": False, "avisos": []})
    if sin_glosario:
        log("Personajes que no están en el glosario: " + ", ".join(
            f"{n} ({c})" for n, c in sorted(sin_glosario.items(), key=lambda x: -x[1])))

    # Las líneas que son solo una acotación ("(REAC)", "[laughs]") no pasan por el modelo si el perfil la unifica
    pendientes = []
    for i, f in enumerate(resultado):
        if not f["original"].strip():
            continue
        if perfil.get("acotacion") and PATRON_SOLO_ACOTACION.match(f["original"]):
            f["traduccion"] = _pos_proceso(perfil["acotacion"], perfil)
        else:
            pendientes.append(i)

    hechas = len(resultado) - len(pendientes)
    progreso(hechas, len(resultado), resultado)
    log(f"Traduciendo {len(pendientes)} líneas…")

    for inicio in range(0, len(pendientes), LINEAS_POR_BLOQUE):
        if cancelado():
            raise InterruptedError
        indices = pendientes[inicio:inicio + LINEAS_POR_BLOQUE]
        bloque = [{"personaje": resultado[i]["personaje"], "dialogo": resultado[i]["original"]} for i in indices]
        previas = [{"personaje": resultado[i]["personaje"], "dialogo": resultado[i]["original"],
                    "traduccion": resultado[i]["traduccion"]}
                   for i in pendientes[max(0, inicio - CONTEXTO_PREVIO):inicio]]
        siguientes = [{"personaje": resultado[i]["personaje"], "dialogo": resultado[i]["original"]}
                      for i in pendientes[inicio + LINEAS_POR_BLOQUE:inicio + LINEAS_POR_BLOQUE + CONTEXTO_SIGUIENTE]]

        try:
            traducciones = _traducir_bloque(motor_llm.SERVIDOR, sistema, bloque, previas, siguientes, glosario)
        except Exception as e:
            log(f"Bloque {inicio // LINEAS_POR_BLOQUE + 1}: {e}. Se reintenta línea por línea.")
            traducciones = [""] * len(bloque)

        # Si faltó alguna línea, se pide sola
        for j, texto in enumerate(traducciones):
            if not texto:
                try:
                    traducciones[j] = _traducir_bloque(motor_llm.SERVIDOR, sistema, [bloque[j]], previas, [], glosario)[0]
                except Exception as e:
                    log(f"No se pudo traducir la línea {indices[j] + 1}: {e}")

        for i, texto in zip(indices, traducciones):
            resultado[i]["traduccion"] = _pos_proceso(texto, perfil)
        hechas += len(indices)
        progreso(hechas, len(resultado), resultado)

    # Revisión: glosario respetado y líneas vacías
    for f in resultado:
        f["dialogo"] = f["traduccion"]
        if f["original"].strip() and not f["traduccion"]:
            f["avisos"].append("Quedó sin traducir")
        for original, destino, _ in glosario.para_bloque([f["original"]]):
            if not _aparece(destino, f["traduccion"]):
                f["avisos"].append(f"Glosario: «{original}» debería ser «{destino}»")
        f["revisar"] = bool(f["avisos"])
    return resultado, sin_glosario
