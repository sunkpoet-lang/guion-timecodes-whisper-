// Guion con Time Codes — interfaz.
// Sin frameworks: cada vista se dibuja como HTML a partir del estado (E) y
// los clics se atienden por delegación con atributos data-accion.

const TOKEN = new URLSearchParams(location.search).get("t");
const $ = (sel, raiz = document) => raiz.querySelector(sel);

const EXT_VIDEO = ["mp4", "mov", "mkv", "avi", "mxf", "wav", "mp3", "m4a", "aac", "flac", "webm", "m4v"];
const EXT_LIBRETO = ["docx", "txt", "srt", "ass"];

const IDIOMAS = [
  ["en", "Inglés"], ["es", "Español"], ["fr", "Francés"], ["ja", "Japonés"], ["pt", "Portugués"],
  ["it", "Italiano"], ["de", "Alemán"], ["ko", "Coreano"], ["zh", "Chino"], ["auto", "Detectar automáticamente"],
];

const MODOS = {
  guion: {
    titulo: "Tengo el guion traducido", icono: "mundo",
    desc: "Ubica cada línea de tu Word en el video y agrega la columna TIME CODE.",
    sale: ["word"],
  },
  asrec: {
    titulo: "Tengo un ASREC sin time code", icono: "microfono",
    desc: "Guion en el mismo idioma que el audio. Alinea comparando el texto, más exacto.",
    sale: ["word"],
  },
  subtitulos: {
    titulo: "No tengo guion", icono: "subtitulos",
    desc: "Genera subtítulos .srt directo de lo que escucha Whisper.",
    sale: ["srt"],
  },
};

const pref = (() => {
  let datos = {};
  try { datos = JSON.parse(localStorage.getItem("preferencias") || "{}"); } catch { /* sin almacenamiento */ }
  return {
    get: (k, d) => (k in datos ? datos[k] : d),
    set: (k, v) => { datos[k] = v; try { localStorage.setItem("preferencias", JSON.stringify(datos)); } catch { /* */ } },
  };
})();

const E = {
  estado: null,
  vista: "timecodes",
  menuModelo: false,
  tc: {
    modo: pref.get("modo", "guion"),
    video: null, guion: null,
    idioma: pref.get("idioma", "en"),
    alineacion: pref.get("alineacion", "proporcional"),
    tarea: "transcribir",
    modelo: pref.get("modelo", null),
    srt: pref.get("srt", false),
    xlsx: pref.get("xlsx", false),
    mmss: pref.get("mmss", false),
    nombre: "",
    carpeta: null,
    trabajo: null,      // id
    datos: null,        // último estado del trabajo
    inicioEtapa: null,
  },
  lib: {
    pestana: "pegar", texto: "", archivo: null, filas: null, formato: null,
    soloRevisar: false, nombre: "", mmss: false, carpeta: null, resultados: [],
  },
};

// ------------------------------------------------------------------
// Utilidades
// ------------------------------------------------------------------

async function api(ruta, opciones = {}) {
  const headers = { "X-Token": TOKEN, ...(opciones.headers || {}) };
  let body = opciones.body;
  if (body && !(body instanceof FormData) && typeof body !== "string") {
    body = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch(ruta, { ...opciones, headers, body });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* */ }
    throw new Error(msg);
  }
  return r.json();
}

function esc(t) {
  return String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function tamano(bytes) {
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1) + " GB";
  if (bytes >= 1024 ** 2) return Math.round(bytes / 1024 ** 2) + " MB";
  return Math.max(1, Math.round(bytes / 1024)) + " KB";
}
const tamanoMB = (mb) => tamano(mb * 1024 ** 2);

function minutos(m) {
  if (m < 1) return "menos de 1 min";
  if (m < 60) return `≈ ${Math.round(m)} min`;
  return `≈ ${Math.floor(m / 60)} h ${Math.round(m % 60)} min`;
}

function reloj(seg) {
  seg = Math.max(0, Math.round(seg));
  const h = Math.floor(seg / 3600), m = Math.floor((seg % 3600) / 60), s = seg % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}

const extension = (ruta) => (ruta.split(".").pop() || "").toLowerCase();
const nombreBase = (nombre) => nombre.replace(/\.[^.]+$/, "");

let temporizadorAviso;
function avisar(texto) {
  const n = $("#notificacion");
  n.textContent = texto;
  n.classList.add("visible");
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => n.classList.remove("visible"), 3200);
}

const escritorio = () => Boolean(E.estado?.escritorio && window.pywebview?.api);
const modeloInfo = (id) => E.estado?.modelos.find((m) => m.id === id);
const hayTrabajoCorriendo = () => E.tc.datos?.estado === "corriendo";

// ------------------------------------------------------------------
// Archivos: diálogo nativo (escritorio) o subida (navegador)
// ------------------------------------------------------------------

async function elegirArchivo(tipo) {
  if (escritorio()) {
    const ruta = await window.pywebview.api.elegir_archivo(tipo);
    if (ruta) asignarArchivo(tipo, await api("/api/archivo", { method: "POST", body: { ruta } }));
    return;
  }
  const input = document.createElement("input");
  input.type = "file";
  input.accept = { video: EXT_VIDEO, word: ["docx"], libreto: EXT_LIBRETO }[tipo].map((e) => "." + e).join(",");
  input.onchange = () => input.files[0] && subirArchivo(tipo, input.files[0]);
  input.click();
}

function subirArchivo(tipo, archivo) {
  const provisional = { nombre: archivo.name, tamano: archivo.size, subiendo: 0 };
  asignarArchivo(tipo, provisional);
  const datos = new FormData();
  datos.append("archivo", archivo);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/subir");
  xhr.setRequestHeader("X-Token", TOKEN);
  xhr.upload.onprogress = (e) => {
    provisional.subiendo = e.loaded / e.total;
    const barra = document.querySelector(`.zona[data-tipo="${tipo}"] .subiendo i`);
    if (barra) barra.style.width = provisional.subiendo * 100 + "%";
  };
  xhr.onload = () => {
    if (xhr.status === 200) asignarArchivo(tipo, JSON.parse(xhr.responseText));
    else { asignarArchivo(tipo, null); avisar("No se pudo cargar el archivo."); }
  };
  xhr.onerror = () => { asignarArchivo(tipo, null); avisar("No se pudo cargar el archivo."); };
  xhr.send(datos);
}

function asignarArchivo(tipo, info) {
  if (tipo === "video") E.tc.video = info;
  else if (tipo === "word") E.tc.guion = info;
  else if (tipo === "libreto") {
    E.lib.archivo = info;
    E.lib.pestana = "archivo";
    // Soltar o elegir el archivo ya lo convierte: no hace falta darle a "Convertir"
    if (info?.ruta && info.subiendo === undefined) { convertirLibreto(); return; }
  }
  dibujar();
}

// Lo llama app.py cuando se sueltan archivos sobre la ventana de escritorio
window.recibirArchivosSoltados = async (rutas) => {
  for (const ruta of rutas) {
    const ext = extension(ruta);
    let tipo = null;
    if (E.vista === "libreto" && EXT_LIBRETO.includes(ext)) tipo = "libreto";
    else if (E.vista === "timecodes" && EXT_VIDEO.includes(ext)) tipo = "video";
    else if (E.vista === "timecodes" && ext === "docx") tipo = "word";
    if (!tipo) { avisar(`No se puede usar un archivo .${ext} aquí.`); continue; }
    try {
      asignarArchivo(tipo, await api("/api/archivo", { method: "POST", body: { ruta } }));
    } catch (e) { avisar(e.message); }
  }
  document.querySelectorAll(".zona.sobre").forEach((z) => z.classList.remove("sobre"));
};

// En el navegador: arrastrar y soltar sube el archivo
document.addEventListener("dragover", (e) => {
  e.preventDefault();
  const zona = e.target.closest?.(".zona");
  document.querySelectorAll(".zona.sobre").forEach((z) => z !== zona && z.classList.remove("sobre"));
  if (zona && !zona.classList.contains("llena")) zona.classList.add("sobre");
});
document.addEventListener("dragleave", (e) => {
  if (!e.relatedTarget) document.querySelectorAll(".zona.sobre").forEach((z) => z.classList.remove("sobre"));
});
document.addEventListener("drop", (e) => {
  e.preventDefault();
  document.querySelectorAll(".zona.sobre").forEach((z) => z.classList.remove("sobre"));
  if (escritorio()) return; // en la ventana de escritorio las rutas llegan por recibirArchivosSoltados
  const archivos = [...(e.dataTransfer?.files || [])];
  const zona = e.target.closest?.(".zona");
  for (const archivo of archivos) {
    const ext = extension(archivo.name);
    let tipo = zona?.dataset.tipo;
    if (!tipo || (tipo === "video" && !EXT_VIDEO.includes(ext)) || (tipo === "word" && ext !== "docx")) {
      tipo = E.vista === "libreto" ? "libreto" : EXT_VIDEO.includes(ext) ? "video" : ext === "docx" ? "word" : null;
    }
    if (tipo) subirArchivo(tipo, archivo);
  }
});

// ------------------------------------------------------------------
// Dibujo general
// ------------------------------------------------------------------

function dibujar() {
  const principal = $("#principal");
  const scroll = principal.scrollTop;
  if (!E.estado) return;
  const vista = { timecodes: vistaTimecodes, libreto: vistaLibreto, modelos: vistaModelos }[E.vista]();
  principal.innerHTML = `<div class="vista">${vista}</div>`;
  principal.scrollTop = scroll;
  pintarIconos(principal);
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("activo", b.dataset.vista === E.vista));
  dibujarLateral();
}

function dibujarLateral() {
  const s = E.estado;
  const hw = s.hardware;
  let punto, linea1, linea2;
  if (s.dispositivo === "cuda") {
    punto = "ok"; linea1 = "<b>GPU lista</b>"; linea2 = hw.gpu.nombre.replace("NVIDIA GeForce ", "");
  } else if (s.gpu_compatible) {
    punto = "aviso"; linea1 = "<b>GPU sin activar</b>"; linea2 = "Toca para activarla";
  } else {
    punto = ""; linea1 = "<b>Usando procesador</b>"; linea2 = `${hw.cpu_nucleos} núcleos · ${hw.ram_gb ?? "?"} GB`;
  }
  $("#equipo-mini").innerHTML =
    `<div class="equipo-fila"><span class="punto ${punto}"></span>${linea1}</div>` +
    `<div class="equipo-fila" style="padding-left:15px">${esc(linea2)}</div>`;
  const instalados = s.modelos.filter((m) => m.instalado).length;
  $("#nav-modelos").textContent = `${instalados}/${s.modelos.length}`;
  $("#version").textContent = "v" + s.version;
  $("#modo-app").textContent = s.escritorio ? "" : "navegador";
  const navTc = document.querySelector('.nav-item[data-vista="timecodes"]');
  navTc.classList.toggle("trabajando", hayTrabajoCorriendo());
}

// ------------------------------------------------------------------
// Vista: Time codes
// ------------------------------------------------------------------

function modeloElegido() {
  const s = E.estado;
  const instalados = s.modelos.filter((m) => m.instalado);
  if (E.tc.modelo && instalados.some((m) => m.id === E.tc.modelo)) return E.tc.modelo;
  if (instalados.some((m) => m.id === s.recomendado)) return s.recomendado;
  const ordenados = [...instalados].sort((a, b) =>
    (b.veredicto === "ok") - (a.veredicto === "ok") || b.precision - a.precision);
  return ordenados[0]?.id || null;
}

function vistaTimecodes() {
  const d = E.tc.datos;
  if (d && d.estado !== "cancelado") {
    return encabezadoTc() + (d.estado === "corriendo" ? panelProgreso(d) : panelResultado(d));
  }
  return encabezadoTc() + seccionModo() + seccionArchivos() + seccionOpciones() + barraGenerar();
}

function encabezadoTc() {
  return `<div class="encabezado"><h1>Time codes con Whisper</h1>
    <p>Sube el video del episodio y tu guion en Word. Whisper escucha el audio y ubica cada línea en el tiempo.</p></div>`;
}

function seccionModo() {
  const tarjetas = Object.entries(MODOS).map(([id, m]) => `
    <button class="modo ${E.tc.modo === id ? "activo" : ""}" data-accion="modo" data-valor="${id}">
      <span class="modo-check">${E.tc.modo === id ? icono("check", 12, 3) : ""}</span>
      <div class="modo-icono">${icono(m.icono, 18)}</div>
      <div class="modo-titulo">${m.titulo}</div>
      <div class="modo-desc">${m.desc}</div>
      <div class="modo-sale">${m.sale.map((t) => t === "word"
        ? `<span class="etiqueta word">${icono("documento", 12)} WORD CON TC</span>`
        : `<span class="etiqueta srt">${icono("subtitulos", 12)} SUBTÍTULOS .SRT</span>`).join("")}</div>
    </button>`).join("");
  return `<section class="seccion"><h2 class="seccion-titulo"><span class="paso-num">1</span>¿Qué necesitas?</h2>
    <div class="opciones-modo">${tarjetas}</div></section>`;
}

function zonaArchivo(tipo, archivo, titulo, ayuda) {
  const iconoTipo = tipo === "video" ? "video" : "documento";
  if (archivo) {
    const subiendo = archivo.subiendo !== undefined;
    return `<div class="zona llena" data-tipo="${tipo}">
      <div class="zona-icono">${icono(iconoTipo, 20)}</div>
      <div class="zona-archivo">
        <div class="zona-nombre" title="${esc(archivo.ruta || archivo.nombre)}">${esc(archivo.nombre)}</div>
        <div class="zona-meta">${subiendo ? "Cargando…" : tamano(archivo.tamano)}</div>
        ${subiendo ? `<div class="subiendo"><i style="width:${archivo.subiendo * 100}%"></i></div>` : ""}
      </div>
      ${subiendo ? "" : `<button class="boton chico" data-accion="elegir" data-valor="${tipo}">Cambiar</button>
      <button class="boton-icono" data-accion="quitar" data-valor="${tipo}" title="Quitar">${icono("x", 16)}</button>`}
    </div>`;
  }
  return `<div class="zona" data-tipo="${tipo}" data-accion="elegir" data-valor="${tipo}">
    <div class="zona-icono">${icono(iconoTipo, 20)}</div>
    <div class="zona-titulo">${titulo}</div>
    <div class="zona-ayuda">Arrastra el archivo aquí o <u>búscalo</u></div>
    <div class="zona-ayuda">${ayuda}</div>
  </div>`;
}

function seccionArchivos() {
  const conGuion = E.tc.modo !== "subtitulos";
  return `<section class="seccion">
    <h2 class="seccion-titulo"><span class="paso-num">2</span>Archivos</h2>
    <div class="archivos">
      ${zonaArchivo("video", E.tc.video, "Video o audio del episodio", "MP4, MOV, MKV, WAV, MP3…")}
      ${conGuion ? zonaArchivo("word", E.tc.guion, "Guion en Word", "Tabla PERSONAJE / DIÁLOGO") : ""}
    </div>
    ${conGuion ? `<details class="detalles"><summary>${icono("derecha", 13)}¿Qué formato debe tener el guion?</summary>
      <div class="aviso info" style="margin-top:10px">${icono("info", 17)}<div>
        Un <b>.docx con una tabla</b> con las columnas <b>PERSONAJE</b> y <b>DIÁLOGO</b> (o CHARACTER / DIALOGUE).
        Es lo que produce <a href="#" data-accion="ir" data-valor="libreto">Convertir libreto</a>.
        Sin tabla, también acepta párrafos con formato <b>PERSONAJE: diálogo</b>.</div></div>
    </details>` : ""}
  </section>`;
}

function avisosModelo(m) {
  const s = E.estado;
  const avisos = [];
  if (!m) return avisos;
  if (E.tc.modo === "subtitulos" && E.tc.tarea === "traducir_a_ingles" && !m.traduce) {
    avisos.push(["rojo", "alerta", `<b>${m.nombre}</b> no sabe traducir. Elige Large v3, Medium o Small para "Traducir a inglés".`]);
  }
  if (m.solo_ingles && E.tc.idioma !== "en") {
    avisos.push(["rojo", "alerta", `<b>${m.nombre}</b> solo entiende audio en inglés.`]);
  }
  if (m.veredicto === "no_cabe") {
    avisos.push(["amarillo", "alerta", s.dispositivo === "cuda"
      ? `<b>${m.nombre}</b> necesita unos ${m.vram_gb} GB de memoria de video y tu GPU tiene ${s.hardware.gpu.vram_gb} GB. Puede fallar o caer al procesador.`
      : `<b>${m.nombre}</b> puede quedarse sin memoria RAM en este equipo.`]);
  } else if (m.veredicto === "lento") {
    avisos.push(["amarillo", "reloj", `Con <b>${m.nombre}</b> en el procesador, un episodio de 22 min tarda ${minutos(m.minutos)}. Prueba un modelo más chico si tienes prisa.`]);
  }
  return avisos;
}

function seccionOpciones() {
  const s = E.estado;
  const conGuion = E.tc.modo !== "subtitulos";
  const idModelo = modeloElegido();
  const m = modeloInfo(idModelo);

  const selectorIdioma = `<select class="entrada" data-campo="idioma">${IDIOMAS.map(([v, t]) =>
    `<option value="${v}" ${E.tc.idioma === v ? "selected" : ""}>${t}</option>`).join("")}</select>`;

  const alineacion = E.tc.modo === "guion" ? `<div class="campo">
      <span class="rotulo">Alineación</span>
      <div class="segmentado">
        <button class="${E.tc.alineacion === "proporcional" ? "activo" : ""}" data-accion="alineacion" data-valor="proporcional">Proporcional</button>
        <button class="${E.tc.alineacion === "texto" ? "activo" : ""}" data-accion="alineacion" data-valor="texto">Por texto</button>
      </div>
      <span class="ayuda">${E.tc.alineacion === "proporcional"
        ? "Para guiones traducidos a otro idioma: reparte las líneas según la duración del habla."
        : "Solo si el guion está en el mismo idioma que el audio: compara el texto línea por línea."}</span>
    </div>` : E.tc.modo === "subtitulos" ? `<div class="campo">
      <span class="rotulo">Tarea</span>
      <div class="segmentado">
        <button class="${E.tc.tarea === "transcribir" ? "activo" : ""}" data-accion="tarea" data-valor="transcribir">Transcribir</button>
        <button class="${E.tc.tarea === "traducir_a_ingles" ? "activo" : ""}" data-accion="tarea" data-valor="traducir_a_ingles">Traducir a inglés</button>
      </div>
      <span class="ayuda">Whisper solo puede traducir <b>a inglés</b>. Útil con audio en japonés u otro idioma.</span>
    </div>` : `<div class="campo"><span class="rotulo">Alineación</span>
      <div class="aviso" style="padding:9px 12px">${icono("check", 16)}<span>Por texto: el guion y el audio están en el mismo idioma.</span></div></div>`;

  const menu = E.menuModelo ? `<div class="menu-modelos">${s.modelos.filter((x) => x.instalado).map((x) => `
      <button class="opcion-modelo ${x.id === idModelo ? "activo" : ""}" data-accion="usar-modelo" data-valor="${x.id}">
        <div><div class="nombre" style="font-weight:600">${x.nombre} ${x.id === s.recomendado ? `<span class="etiqueta acento">${icono("estrella", 11)} Recomendado</span>` : ""}</div>
          <div class="detalle ayuda">${esc(x.nota)}</div></div>
        <div class="der">${x.veredicto === "no_cabe" ? '<span class="etiqueta aviso">No cabe</span>' : minutos(x.minutos)}<br><span>por episodio</span></div>
      </button>`).join("")}
      <div class="separador"></div>
      <button class="opcion-modelo mas" data-accion="ir" data-valor="modelos">${icono("descarga", 16)} Descargar otros modelos…</button>
    </div>` : "";

  const recomendadoFalta = s.recomendado !== idModelo && !modeloInfo(s.recomendado)?.instalado;
  const avisos = avisosModelo(m);
  const gpuSinActivar = s.gpu_compatible && !s.cuda.listo;

  const carpetaFila = escritorio() ? `<div class="campo">
      <span class="rotulo">Guardar en</span>
      <div class="fila-carpeta">
        <div class="entrada" title="${esc(E.tc.carpeta || "")}">${E.tc.carpeta ? esc(E.tc.carpeta) : "La misma carpeta del video"}</div>
        <button class="boton" data-accion="carpeta-tc">${icono("carpeta", 15)} Cambiar</button>
        ${E.tc.carpeta ? `<button class="boton-icono" data-accion="carpeta-tc-quitar" title="Volver a la carpeta del video">${icono("x", 15)}</button>` : ""}
      </div></div>` : "";

  const base = E.tc.video ? nombreBase(E.tc.video.nombre) : "episodio";
  const sugerido = conGuion ? `${base}_TC.docx` : `${base}.srt`;

  return `<section class="seccion">
    <h2 class="seccion-titulo"><span class="paso-num">3</span>Opciones</h2>
    ${gpuSinActivar ? `<div class="aviso amarillo" style="margin-bottom:16px">${icono("rayo", 17)}
      <div><b>Tu ${esc(s.hardware.gpu.nombre)} no se está usando.</b> Faltan librerías de NVIDIA. Con la GPU activada, Whisper es mucho más rápido.</div>
      <div class="acciones"><button class="boton chico primario" data-accion="ir" data-valor="modelos">Activar GPU</button></div></div>` : ""}
    <div class="rejilla">
      <div class="campo"><label>Idioma del audio</label>${selectorIdioma}
        <span class="ayuda">El idioma que se habla en el video, no el del guion.</span></div>
      ${alineacion}
      <div class="campo ancho" style="position:relative">
        <span class="rotulo">Modelo de Whisper</span>
        ${m ? `<button class="modelo-elegido" data-accion="menu-modelo">
          <div><div class="nombre">${m.nombre} ${m.id === s.recomendado ? `<span class="etiqueta acento">${icono("estrella", 11)} Recomendado para tu equipo</span>` : ""}</div>
            <div class="detalle">${s.dispositivo === "cuda" ? "En GPU" : "En procesador"} · ${minutos(m.minutos)} por episodio de 22 min</div></div>
          <span class="chevron">${icono("abajo", 16)}</span></button>` : `<div class="aviso rojo">${icono("alerta", 17)}<div>No hay modelos instalados.</div>
            <div class="acciones"><button class="boton chico primario" data-accion="ir" data-valor="modelos">Descargar un modelo</button></div></div>`}
        ${menu}
        ${recomendadoFalta ? `<span class="ayuda">Para tu equipo recomendamos <b>${modeloInfo(s.recomendado).nombre}</b> (${tamanoMB(modeloInfo(s.recomendado).tamano_mb)}).
          <a href="#" data-accion="descargar-recomendado">Descargarlo</a></span>` : ""}
        ${avisos.map(([c, i, t]) => `<div class="aviso ${c}">${icono(i, 17)}<div>${t}</div></div>`).join("")}
      </div>
      ${conGuion ? `
      <label class="interruptor"><input type="checkbox" data-campo="mmss" ${E.tc.mmss ? "checked" : ""}><span class="pista"></span>
        <span class="interruptor-texto"><b>TIME CODE en formato MMSS</b><span>Convención de doblaje: 0114 = 1 min 14 s, en vez de 00:01:14,300.</span></span></label>
      <label class="interruptor"><input type="checkbox" data-campo="srt" ${E.tc.srt ? "checked" : ""}><span class="pista"></span>
        <span class="interruptor-texto"><b>Exportar también subtítulos .srt</b><span>Para revisar la sincronía en un reproductor de video.</span></span></label>
      <label class="interruptor"><input type="checkbox" data-campo="xlsx" ${E.tc.xlsx ? "checked" : ""}><span class="pista"></span>
        <span class="interruptor-texto"><b>Exportar también en Excel (.xlsx)</b><span>Las mismas 3 columnas: T.C., PERSONAJE y DIÁLOGO.</span></span></label>` : ""}
      <div class="campo"><label>Nombre del archivo</label>
        <input class="entrada" data-campo="nombre" value="${esc(E.tc.nombre)}" placeholder="${esc(sugerido)}" spellcheck="false"></div>
      ${carpetaFila}
    </div>
  </section>`;
}

function faltantes() {
  const f = [];
  if (!E.tc.video) f.push("el video");
  if (E.tc.modo !== "subtitulos" && !E.tc.guion) f.push("el guion en Word");
  if (!modeloElegido()) f.push("un modelo");
  if ([E.tc.video, E.tc.guion].some((a) => a?.subiendo !== undefined)) f.push("que termine de cargar");
  return f;
}

function barraGenerar() {
  const f = faltantes();
  const m = modeloInfo(modeloElegido());
  const resumen = f.length
    ? `<span class="falta">Falta ${f.join(" y ")}.</span>`
    : `<b>${esc(E.tc.video.nombre)}</b>${E.tc.modo !== "subtitulos" ? ` + <b>${esc(E.tc.guion.nombre)}</b>` : ""}
       → ${E.tc.modo === "subtitulos" ? "subtítulos .srt" : "Word con TIME CODE"} · ${m.nombre}, ${minutos(m.minutos)}`;
  return `<div class="barra-accion"><div class="resumen">${resumen}</div>
    <button class="boton primario grande" data-accion="generar" ${f.length ? "disabled" : ""}>${icono("onda", 17)} Generar</button></div>`;
}

const ETAPAS = {
  guion: ["Cargando modelo", "Transcribiendo audio", "Alineando el guion", "Guardando"],
  subtitulos: ["Cargando modelo", "Transcribiendo audio", "Guardando"],
};

function panelProgreso(d) {
  const etapas = E.tc.modo === "subtitulos" ? ETAPAS.subtitulos : ETAPAS.guion;
  let actual = { "Iniciando": 0, "Cargando modelo": 0, "Transcribiendo audio": 1, "Alineando el guion": 2,
    "Recuperando desde el respaldo": etapas.length - 2 }[d.etapa] ?? 0;
  const transcribiendo = d.etapa === "Transcribiendo audio";
  const pct = Math.round((d.progreso || 0) * 100);

  let restante = "";
  if (transcribiendo && E.tc.inicioEtapa && d.progreso > 0.03) {
    const hecho = (Date.now() / 1000 - E.tc.inicioEtapa.t) ;
    const avance = d.progreso - E.tc.inicioEtapa.p;
    if (avance > 0.01) restante = ` · quedan ≈ ${reloj(hecho / avance * (1 - d.progreso))}`;
  }

  const lista = etapas.map((nombre, i) => {
    const clase = i < actual ? "hecha" : i === actual ? "actual" : "";
    const p = i === actual && (transcribiendo || d.etapa === "Alineando el guion") ? pct : 0;
    return `<div class="etapa ${clase}" style="--p:${p}%">${nombre}</div>`;
  }).join("");

  const indeterminada = !transcribiendo && d.etapa !== "Alineando el guion";
  return `<section class="seccion progreso-panel">
    <div class="progreso-cabecera">
      <span class="giro">${icono("cargando", 22)}</span>
      <div><h2>${esc(d.etapa)}…</h2><div class="tiempo">${reloj(d.transcurrido)} transcurrido${restante}</div></div>
      <button class="boton peligro" style="margin-left:auto" data-accion="cancelar">${icono("parar", 14)} Cancelar</button>
    </div>
    <div class="etapas">${lista}</div>
    <div class="barra ${indeterminada ? "indeterminada" : ""}"><i style="width:${pct}%"></i></div>
    ${d.aviso_cpu ? `<div class="aviso amarillo" style="margin-top:14px">${icono("alerta", 17)}<div>
      <b>La GPU falló y Whisper siguió en el procesador.</b> Va a tardar más. Revisa la GPU en <a href="#" data-accion="ir" data-valor="modelos">Modelos y equipo</a>.</div></div>` : ""}
    <details class="detalles" ${pref.get("verRegistro", false) ? "open" : ""} data-accion="ver-registro">
      <summary>${icono("derecha", 13)}Ver registro</summary>
      <div class="registro" id="registro">${esc(d.log.join("\n"))}</div>
    </details>
  </section>`;
}

function filaArchivoSalida(r) {
  const tipo = { srt: "srt", xlsx: "excel" }[r.tipo] || "word";
  const iconoTipo = { srt: "subtitulos", excel: "hoja" }[tipo] || "documento";
  const acciones = escritorio()
    ? `<button class="boton chico" data-accion="abrir" data-valor="${esc(r.ruta)}">${icono("abrir", 14)} Abrir</button>
       <button class="boton chico fantasma" data-accion="mostrar" data-valor="${esc(r.ruta)}">${icono("carpeta", 14)} Mostrar en carpeta</button>`
    : `<a class="boton chico primario" href="/api/descargar?t=${TOKEN}&ruta=${encodeURIComponent(r.ruta)}">${icono("descarga", 14)} Descargar</a>`;
  return `<div class="archivo-salida">
    <div class="zona-icono" style="width:38px;height:38px;border-radius:10px;display:grid;place-items:center;color:var(--${tipo});background:color-mix(in srgb, var(--${tipo}) 13%, transparent)">${icono(iconoTipo, 19)}</div>
    <div class="zona-archivo"><div class="zona-nombre">${esc(r.nombre)}</div>
      <div class="zona-meta">${escritorio() ? esc(r.ruta) : tamano(r.tamano)}</div></div>
    ${acciones}</div>`;
}

function panelResultado(d) {
  if (d.estado === "error") {
    return `<section class="seccion">
      <div class="aviso rojo">${icono("alerta", 18)}<div><b>No se pudo terminar.</b><br>${esc(d.error)}</div>
        <div class="acciones"><button class="boton" data-accion="volver">Volver</button></div></div>
      <div class="registro">${esc(d.log.join("\n"))}</div></section>`;
  }
  const lineas = d.log.filter((l) => /Atención|Subtítulos generados|líneas/.test(l));
  return `<section class="seccion">
    <div class="resultado-cabecera"><div class="resultado-icono">${icono("check", 22, 2.5)}</div>
      <div><h2>¡Listo!</h2><p>Terminó en ${reloj(d.transcurrido)}${d.idioma_detectado ? ` · idioma detectado: ${esc(d.idioma_detectado)}` : ""}.</p></div>
      <button class="boton" style="margin-left:auto" data-accion="volver">${icono("reintentar", 14)} Nuevo trabajo</button></div>
    ${d.resultados.map(filaArchivoSalida).join("")}
    ${lineas.filter((l) => l.startsWith("Atención")).map((l) =>
      `<div class="aviso amarillo" style="margin-top:12px">${icono("alerta", 17)}<div>${esc(l)}</div></div>`).join("")}
    ${d.aviso_cpu ? `<div class="aviso amarillo" style="margin-top:12px">${icono("alerta", 17)}<div>Se usó el procesador porque la GPU falló. Revisa <a href="#" data-accion="ir" data-valor="modelos">Modelos y equipo</a>.</div></div>` : ""}
    <details class="detalles"><summary>${icono("derecha", 13)}Ver registro</summary><div class="registro">${esc(d.log.join("\n"))}</div></details>
  </section>`;
}

async function generar() {
  const t = E.tc;
  try {
    const { id } = await api("/api/trabajos", {
      method: "POST",
      body: {
        modo: t.modo, video: t.video.ruta, guion: t.modo !== "subtitulos" ? t.guion.ruta : null,
        idioma: t.idioma, alineacion: t.alineacion, modelo: modeloElegido(), tarea: t.tarea,
        exportar_srt: t.srt, exportar_xlsx: t.xlsx, formato_mmss: t.mmss, nombre_salida: t.nombre, carpeta_salida: t.carpeta,
      },
    });
    t.trabajo = id;
    t.inicioEtapa = null;
    t.datos = { estado: "corriendo", etapa: "Iniciando", progreso: 0, log: [], transcurrido: 0 };
    dibujar();
    seguirTrabajo();
  } catch (e) { avisar(e.message); }
}

async function seguirTrabajo() {
  const t = E.tc;
  while (t.trabajo) {
    try {
      const d = await api(`/api/trabajos/${t.trabajo}`);
      if (d.etapa === "Transcribiendo audio" && !t.inicioEtapa) t.inicioEtapa = { t: Date.now() / 1000, p: d.progreso };
      const cambioEstado = d.estado !== t.datos?.estado;
      t.datos = d;
      if (E.vista === "timecodes") {
        const registro = $("#registro");
        const abajo = registro && registro.scrollHeight - registro.scrollTop - registro.clientHeight < 30;
        dibujar();
        const nuevo = $("#registro");
        if (nuevo && (abajo || !registro)) nuevo.scrollTop = nuevo.scrollHeight;
      } else dibujarLateral();
      if (d.estado !== "corriendo") {
        if (cambioEstado && d.estado === "listo" && E.vista !== "timecodes") avisar("Time codes listos.");
        if (d.estado === "cancelado") { t.datos = null; avisar("Trabajo cancelado."); dibujar(); }
        t.trabajo = null;
        break;
      }
    } catch { /* reintenta */ }
    await new Promise((r) => setTimeout(r, 700));
  }
}

// ------------------------------------------------------------------
// Vista: Convertir libreto
// ------------------------------------------------------------------

function vistaLibreto() {
  const L = E.lib;
  const entrada = L.pestana === "pegar"
    ? `<textarea class="entrada" data-campo-lib="texto" spellcheck="false" placeholder="Pega aquí el libreto, un .srt o un .ass… o arrastra el archivo a esta ventana.&#10;&#10;1 (10:00:02:00)&#10;JEREMY&#9;¡Requin!&#10;PETIT DRAGON&#9;¡Requin!">${esc(L.texto)}</textarea>
      <div class="ayuda" style="margin-top:8px">${icono("subir", 13)} También puedes <b>arrastrar un archivo</b> (.docx, .txt, .srt o .ass) a cualquier parte de esta página: se convierte solo.</div>`
    : `<div class="archivos">${zonaArchivo("libreto", L.archivo, "Libreto o subtítulos", ".docx, .txt, .srt o .ass")}</div>`;

  const puede = L.pestana === "pegar" ? L.texto.trim() : L.archivo && L.archivo.subiendo === undefined;

  let tabla = "";
  if (L.filas) {
    const revisar = L.filas.filter((f) => f.revisar).length;
    const formatos = {
      libreto: "libreto tradicional", guion_numerado: "guion numerado", guion_broadcast: 'guion "as broadcast"',
      guion_estilos: "guion con estilos de Word", tabla_word: "tabla de Word", srt: "subtítulos .srt", ass: "subtítulos .ass",
    };
    const conTc = L.filas.some((f) => f.timecode);
    const filas = L.filas.map((f, i) => (L.soloRevisar && !f.revisar) ? "" : `
      <tr class="${f.revisar ? "revisar" : ""}" data-fila="${i}">
        <td class="num">${i + 1}</td>
        <td class="tc" contenteditable="plaintext-only" data-col="timecode">${esc(f.timecode)}</td>
        <td class="pj" contenteditable="plaintext-only" data-col="personaje">${esc(f.personaje)}</td>
        <td contenteditable="plaintext-only" data-col="dialogo">${esc(f.dialogo)}</td>
        <td class="acc"><button class="boton-icono" data-accion="fila-mas" data-valor="${i}" title="Insertar fila debajo">${icono("mas", 15)}</button><button class="boton-icono" data-accion="fila-borrar" data-valor="${i}" title="Borrar fila">${icono("basura", 15)}</button></td>
      </tr>`).join("");

    tabla = `<section class="seccion">
      <h2 class="seccion-titulo"><span class="paso-num">2</span>Revisa y corrige<span class="extra">Haz clic en cualquier celda para editarla</span></h2>
      <div class="tabla-marco">
        <div class="tabla-herramientas">
          <span class="etiqueta neutra">${formatos[L.formato] || L.formato}</span>
          <span>${L.filas.length} líneas</span>
          ${revisar ? `<button class="boton chico ${L.soloRevisar ? "primario" : ""}" data-accion="solo-revisar">${icono("filtro", 13)} ${revisar} por revisar</button>` : `<span class="etiqueta ok">${icono("check", 12)} Sin dudas</span>`}
          <button class="boton chico fantasma" style="margin-left:auto" data-accion="fila-mas" data-valor="${L.filas.length - 1}">${icono("mas", 14)} Agregar fila</button>
        </div>
        <div class="tabla-scroll"><table class="libreto">
          <thead><tr><th></th><th>TIME CODE</th><th>PERSONAJE</th><th>DIÁLOGO</th><th></th></tr></thead>
          <tbody>${filas}</tbody></table></div>
      </div>
      ${["srt", "ass"].includes(L.formato) ? `<div class="aviso info" style="margin-top:12px">${icono("info", 17)}<div>El TIME CODE viene del archivo. Asigna cada <b>PERSONAJE</b> viendo el video antes de exportar.</div></div>`
        : !conTc ? `<div class="aviso info" style="margin-top:12px">${icono("info", 17)}<div>La columna TIME CODE queda vacía: se llena después en <a href="#" data-accion="ir" data-valor="timecodes">Time codes</a>, con el video.</div></div>` : ""}
    </section>

    <section class="seccion">
      <h2 class="seccion-titulo"><span class="paso-num">3</span>Exportar</h2>
      <div class="rejilla">
        <div class="campo"><label>Nombre del archivo</label>
          <input class="entrada" data-campo-lib="nombre" value="${esc(L.nombre)}" placeholder="${esc(L.archivo && L.pestana === "archivo" ? nombreBase(L.archivo.nombre) + "_3columnas" : "guion_3_columnas")}" spellcheck="false">
          <span class="ayuda">La extensión (.docx o .xlsx) se pone sola.</span></div>
        ${escritorio() ? `<div class="campo"><span class="rotulo">Guardar en</span><div class="fila-carpeta">
          <div class="entrada">${L.carpeta ? esc(L.carpeta) : L.archivo?.ruta && L.pestana === "archivo" ? "La misma carpeta del archivo" : "Carpeta de salidas de la app"}</div>
          <button class="boton" data-accion="carpeta-lib">${icono("carpeta", 15)} Cambiar</button></div></div>` : ""}
        ${conTc ? `<label class="interruptor"><input type="checkbox" data-campo-lib="mmss" ${L.mmss ? "checked" : ""}><span class="pista"></span>
          <span class="interruptor-texto"><b>TIME CODE en formato MMSS</b><span>0114 = 1 min 14 s, en vez de 00:01:14,300.</span></span></label>` : ""}
      </div>
      <div style="display:flex; gap:10px; margin-top:18px; align-items:center">
        <button class="boton primario grande" data-accion="exportar" data-valor="docx">${icono("documento", 17)} Exportar a Word</button>
        <button class="boton grande" data-accion="exportar" data-valor="xlsx">${icono("hoja", 17)} Exportar a Excel</button>
      </div>
      ${L.resultados.length ? `<div style="margin-top:14px">${L.resultados.map(filaArchivoSalida).join("")}</div>` : ""}
    </section>`;
  }

  return `<div class="encabezado"><h1>Convertir libreto a 3 columnas</h1>
      <p>Convierte un libreto tradicional, un guion numerado o "as broadcast", un Word con tabla (como los ASR de CaptionMax) o subtítulos .srt / .ass en una tabla T.C. · PERSONAJE · DIÁLOGO para Word o Excel.</p></div>
    <section class="seccion">
      <h2 class="seccion-titulo"><span class="paso-num">1</span>Texto de entrada</h2>
      <div class="pestanas">
        <button class="${L.pestana === "pegar" ? "activo" : ""}" data-accion="pestana" data-valor="pegar">Pegar texto</button>
        <button class="${L.pestana === "archivo" ? "activo" : ""}" data-accion="pestana" data-valor="archivo">Desde un archivo</button>
      </div>
      ${entrada}
      <div style="margin-top:14px; display:flex; gap:10px">
        <button class="boton primario" data-accion="convertir" ${puede ? "" : "disabled"}>${icono("tabla", 16)} Convertir</button>
        ${L.filas ? `<button class="boton fantasma" data-accion="limpiar-lib">Empezar de nuevo</button>` : ""}
      </div>
    </section>
    ${tabla}`;
}

async function convertirLibreto() {
  const L = E.lib;
  try {
    const cuerpo = L.pestana === "pegar" ? { texto: L.texto } : { ruta: L.archivo.ruta };
    const r = await api("/api/libreto/convertir", { method: "POST", body: cuerpo });
    L.filas = r.filas; L.formato = r.formato; L.resultados = []; L.soloRevisar = false;
    dibujar();
    setTimeout(() => document.querySelector(".tabla-marco")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  } catch (e) { avisar(e.message); }
}

async function exportarLibreto(tipo = "docx") {
  const L = E.lib;
  try {
    const r = await api("/api/libreto/exportar", {
      method: "POST",
      body: { filas: L.filas, nombre: L.nombre, tipo, formato_mmss: L.mmss, carpeta: L.carpeta,
        origen: L.pestana === "archivo" ? L.archivo?.ruta : null },
    });
    L.resultados = [r, ...L.resultados.filter((x) => x.ruta !== r.ruta)];
    dibujar();
    avisar(`${tipo === "xlsx" ? "Excel" : "Word"} generado (${r.lineas} líneas).`);
  } catch (e) { avisar(e.message); }
}

// ------------------------------------------------------------------
// Vista: Modelos y equipo
// ------------------------------------------------------------------

function medidor(valor) {
  return `<span class="medidor">${[1, 2, 3, 4, 5].map((i) =>
    `<i class="${valor >= i ? "on" : valor >= i - 0.5 ? "medio" : ""}"></i>`).join("")}</span>`;
}

function vistaModelos() {
  const s = E.estado;
  const hw = s.hardware;
  const gpu = hw.gpu;

  const datoGpu = gpu
    ? `<div class="dato-valor">${esc(gpu.nombre)}</div><div class="dato-extra">${gpu.vram_gb} GB de memoria de video · driver ${esc(gpu.driver)}</div>`
    : `<div class="dato-valor">${esc(hw.otra_gpu || "No detectada")}</div><div class="dato-extra">${hw.otra_gpu ? "No es NVIDIA: Whisper no puede usarla" : "Se usará el procesador"}</div>`;

  let aceleracion;
  const cj = s.cuda_instalacion;
  if (cj.activo) {
    const pct = cj.total ? cj.hechos / cj.total * 100 : 0;
    aceleracion = `<div class="aviso info">${icono("descarga", 17)}<div style="flex:1">
      <b>${esc(cj.etapa)}</b> <span class="ayuda">${cj.total ? `${tamano(cj.hechos)} de ${tamano(cj.total)}` : ""}</span>
      <div class="barra" style="margin-top:8px"><i style="width:${pct}%"></i></div></div>
      <div class="acciones"><button class="boton chico" data-accion="cuda-cancelar">Cancelar</button></div></div>`;
  } else if (s.gpu_compatible && s.cuda.listo) {
    aceleracion = `<div class="aviso verde">${icono("rayo", 17)}<div><b>GPU activa.</b> Whisper usa tu ${esc(gpu.nombre)} (${s.compute_type}).
      ${s.cuda.origen === "app" ? `<br><span class="ayuda">Librerías de NVIDIA instaladas por la app: ${tamanoMB(s.cuda.tamano_mb)}.</span>` : `<br><span class="ayuda">Usando las librerías CUDA instaladas en el sistema.</span>`}</div>
      ${s.cuda.origen === "app" ? `<div class="acciones"><button class="boton chico fantasma" data-accion="cuda-borrar">Quitar</button></div>` : ""}</div>`;
  } else if (s.gpu_compatible) {
    const conGpu = modeloInfo(s.recomendado_con_gpu);
    aceleracion = `<div class="aviso amarillo">${icono("rayo", 17)}<div>
      <b>Tu ${esc(gpu.nombre)} todavía no se usa.</b> Faltan las librerías de NVIDIA (cuBLAS y cuDNN), que el driver no trae.
      La app las descarga del repositorio oficial de NVIDIA en PyPI: son unos 1.2 GB de descarga, una sola vez.
      ${conGpu ? `<br>Con GPU podrías usar <b>${conGpu.nombre}</b>, el más preciso para tu equipo.` : ""}
      ${cj.error ? `<br><span style="color:var(--error)">${esc(cj.error)}</span>` : ""}</div>
      <div class="acciones"><button class="boton primario" data-accion="cuda-instalar">${icono("rayo", 15)} Activar GPU</button></div></div>`;
  } else if (hw.apple_silicon) {
    aceleracion = `<div class="aviso info">${icono("info", 17)}<div>En Mac, Whisper corre en el procesador (Apple Silicon es bastante rápido para esto). Las recomendaciones ya lo tienen en cuenta.</div></div>`;
  } else {
    aceleracion = `<div class="aviso info">${icono("info", 17)}<div>${hw.otra_gpu ? `Se detectó <b>${esc(hw.otra_gpu)}</b>, pero Whisper solo acelera con tarjetas NVIDIA.` : "No se detectó una tarjeta NVIDIA."}
      Se usará el procesador; las recomendaciones ya lo tienen en cuenta.</div></div>`;
  }

  const dispositivo = s.dispositivo === "cuda" ? "GPU" : "procesador";
  const tarjetas = s.modelos.map((m) => {
    const insignias = [
      m.id === s.recomendado ? `<span class="etiqueta acento">${icono("estrella", 11)} Recomendado</span>` : "",
      m.instalado ? `<span class="etiqueta ok">${icono("check", 11, 3)} ${m.origen === "incluido" ? "Incluido" : "Instalado"}</span>` : "",
      m.solo_ingles ? `<span class="etiqueta neutra">Solo inglés</span>` : "",
      !m.traduce && !m.solo_ingles ? `<span class="etiqueta neutra">No traduce</span>` : "",
    ].join("");

    const estimado = m.veredicto === "no_cabe"
      ? `<span class="etiqueta aviso">${s.dispositivo === "cuda" ? `Necesita ${m.vram_gb} GB de VRAM` : "Poca RAM para este modelo"}</span>`
      : `<span ${m.veredicto === "lento" ? 'style="color:var(--aviso)"' : ""}>${minutos(m.minutos)} por episodio<br>en ${dispositivo}${m.veredicto === "lento" ? " (lento)" : ""}</span>`;

    let accion;
    if (m.descarga && !m.descarga.error) {
      const pct = m.descarga.total ? m.descarga.hechos / m.descarga.total * 100 : 0;
      accion = `<div class="progreso-mini"><div class="barra"><i style="width:${pct}%"></i></div>
        <div class="texto"><span>${tamano(m.descarga.hechos)} / ${tamano(m.descarga.total)}</span>
        <a href="#" data-accion="modelo-cancelar" data-valor="${m.id}">Cancelar</a></div></div>`;
    } else if (m.descarga?.error) {
      accion = `<span class="etiqueta error" title="${esc(m.descarga.error)}">Error al descargar</span>
        <button class="boton chico" data-accion="modelo-descargar" data-valor="${m.id}">${icono("reintentar", 13)} Reintentar</button>`;
    } else if (m.instalado) {
      accion = `<div style="display:flex; gap:6px">
        <button class="boton chico" data-accion="usar-modelo-ir" data-valor="${m.id}">Usar</button>
        ${m.origen !== "incluido" ? `<button class="boton-icono" data-accion="modelo-borrar" data-valor="${m.id}" title="Borrar del disco">${icono("basura", 15)}</button>` : ""}</div>`;
    } else {
      accion = `<button class="boton chico ${m.id === s.recomendado ? "primario" : ""}" data-accion="modelo-descargar" data-valor="${m.id}">${icono("descarga", 14)} Descargar · ${tamanoMB(m.tamano_mb)}</button>`;
    }

    return `<div class="tarjeta-modelo ${m.id === s.recomendado ? "recomendado" : ""}">
      <div><div class="titulo">${m.nombre} ${insignias}</div>
        <div class="nota">${esc(m.nota)}</div>
        <div class="meta"><span>${tamanoMB(m.tamano_mb)}</span>
          ${m.origen === "cache_hf" ? "<span>ya estaba descargado (caché de Hugging Face)</span>" : ""}
          <a href="#" data-accion="web" data-valor="${esc(m.url)}">Ver en Hugging Face ↗</a></div></div>
      <div class="medidores"><span>Precisión</span>${medidor(m.precision)}<span>Velocidad</span>${medidor(m.velocidad)}</div>
      <div class="lado"><div class="estimado">${estimado}</div>${accion}</div>
    </div>`;
  }).join("");

  return `<div class="encabezado"><h1>Modelos y equipo</h1>
      <p>La app revisa tu hardware para recomendarte el modelo de Whisper que mejor rinde en este equipo. Los modelos se descargan de las páginas oficiales en Hugging Face.</p></div>
    <section class="seccion">
      <h2 class="seccion-titulo">Tu equipo<span class="extra">${esc(hw.sistema)}</span></h2>
      <div class="equipo-grande">
        <div class="dato"><div class="dato-rotulo">${icono("chip", 14)} Procesador</div>
          <div class="dato-valor">${esc(hw.cpu_nombre || "Desconocido")}</div><div class="dato-extra">${hw.cpu_nucleos} núcleos lógicos</div></div>
        <div class="dato"><div class="dato-rotulo">${icono("memoria", 14)} Memoria</div>
          <div class="dato-valor">${hw.ram_gb ?? "?"} GB de RAM</div><div class="dato-extra">&nbsp;</div></div>
        <div class="dato"><div class="dato-rotulo">${icono("gpu", 14)} Tarjeta de video</div>${datoGpu}</div>
      </div>
      ${aceleracion}
    </section>
    <section class="seccion">
      <h2 class="seccion-titulo">Modelos de Whisper<span class="extra">Tiempos estimados para un episodio de 22 min</span></h2>
      <div class="lista-modelos">${tarjetas}</div>
    </section>`;
}

// ------------------------------------------------------------------
// Estado general y sondeo
// ------------------------------------------------------------------

async function refrescarEstado() {
  E.estado = await api("/api/estado");
}

let sondeando = false;
async function sondearDescargas() {
  if (sondeando) return;
  sondeando = true;
  while (true) {
    await new Promise((r) => setTimeout(r, 900));
    try { await refrescarEstado(); } catch { continue; }
    const activas = E.estado.cuda_instalacion.activo || E.estado.modelos.some((m) => m.descarga && !m.descarga.error);
    if (E.vista === "modelos") dibujar(); else dibujarLateral();
    if (!activas) break;
  }
  sondeando = false;
  if (E.vista !== "timecodes" || !hayTrabajoCorriendo()) dibujar();
}

// ------------------------------------------------------------------
// Eventos
// ------------------------------------------------------------------

const ACCIONES = {
  async ir(v) { E.vista = v; E.menuModelo = false; dibujar(); $("#principal").scrollTop = 0; },
  modo(v) { E.tc.modo = v; pref.set("modo", v); if (v === "asrec") E.tc.alineacion = "texto"; else if (v === "guion") E.tc.alineacion = pref.get("alineacion", "proporcional"); dibujar(); },
  alineacion(v) { E.tc.alineacion = v; pref.set("alineacion", v); dibujar(); },
  tarea(v) { E.tc.tarea = v; dibujar(); },
  elegir(v) { elegirArchivo(v).catch((e) => avisar(e.message)); },
  quitar(v) { asignarArchivo(v, null); },
  "menu-modelo"() { E.menuModelo = !E.menuModelo; dibujar(); },
  "usar-modelo"(v) { E.tc.modelo = v; pref.set("modelo", v); E.menuModelo = false; dibujar(); },
  "usar-modelo-ir"(v) { E.tc.modelo = v; pref.set("modelo", v); E.vista = "timecodes"; dibujar(); avisar(`Se usará ${modeloInfo(v).nombre}.`); },
  async "descargar-recomendado"() { await ACCIONES["modelo-descargar"](E.estado.recomendado); E.vista = "modelos"; dibujar(); },
  async "carpeta-tc"() { const c = await window.pywebview.api.elegir_carpeta(); if (c) { E.tc.carpeta = c; dibujar(); } },
  "carpeta-tc-quitar"() { E.tc.carpeta = null; dibujar(); },
  async "carpeta-lib"() { const c = await window.pywebview.api.elegir_carpeta(); if (c) { E.lib.carpeta = c; dibujar(); } },
  generar,
  async cancelar() { if (E.tc.trabajo && confirm("¿Cancelar el trabajo en curso?")) await api(`/api/trabajos/${E.tc.trabajo}/cancelar`, { method: "POST" }); },
  volver() { E.tc.datos = null; E.tc.trabajo = null; dibujar(); },
  async abrir(v) { await api("/api/abrir", { method: "POST", body: { ruta: v } }).catch((e) => avisar(e.message)); },
  async mostrar(v) { await api("/api/abrir", { method: "POST", body: { ruta: v, carpeta: true } }).catch((e) => avisar(e.message)); },
  async web(v) {
    if (escritorio()) await api("/api/abrir-web", { method: "POST", body: { ruta: v } });
    else window.open(v, "_blank");
  },
  pestana(v) { E.lib.pestana = v; dibujar(); },
  convertir: convertirLibreto,
  exportar: exportarLibreto,
  "limpiar-lib"() { Object.assign(E.lib, { texto: "", archivo: null, filas: null, formato: null, resultados: [], nombre: "" }); dibujar(); },
  "solo-revisar"() { E.lib.soloRevisar = !E.lib.soloRevisar; dibujar(); },
  "fila-mas"(v) { E.lib.filas.splice(Number(v) + 1, 0, { timecode: "", personaje: "", dialogo: "", revisar: false }); dibujar(); },
  "fila-borrar"(v) { E.lib.filas.splice(Number(v), 1); dibujar(); },
  async "modelo-descargar"(v) {
    await api(`/api/modelos/${v}/descargar`, { method: "POST" }).catch((e) => avisar(e.message));
    await refrescarEstado(); dibujar(); sondearDescargas();
  },
  async "modelo-cancelar"(v) { await api(`/api/modelos/${v}/cancelar`, { method: "POST" }); },
  async "modelo-borrar"(v) {
    const m = modeloInfo(v);
    if (!confirm(`¿Borrar ${m.nombre} del disco? Libera ${tamanoMB(m.tamano_mb)}. Lo puedes volver a descargar cuando quieras.`)) return;
    await api(`/api/modelos/${v}`, { method: "DELETE" }).catch((e) => avisar(e.message));
    await refrescarEstado(); dibujar();
  },
  async "cuda-instalar"() { await api("/api/cuda/instalar", { method: "POST" }); await refrescarEstado(); dibujar(); sondearDescargas(); },
  async "cuda-cancelar"() { await api("/api/cuda/cancelar", { method: "POST" }); },
  async "cuda-borrar"() {
    if (!confirm("¿Quitar las librerías de NVIDIA? Whisper volverá a usar el procesador. Si alguna está en uso, se borrará al cerrar la app.")) return;
    await api("/api/cuda", { method: "DELETE" }); await refrescarEstado(); dibujar();
  },
  "ver-registro"() { /* se guarda en el evento toggle */ },
};

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-accion], [data-vista], [data-ir]");
  if (!el) {
    if (E.menuModelo && !e.target.closest(".menu-modelos")) { E.menuModelo = false; dibujar(); }
    return;
  }
  if (el.dataset.vista || el.dataset.ir) { ACCIONES.ir(el.dataset.vista || el.dataset.ir); return; }
  const accion = el.dataset.accion;
  if (accion === "ver-registro") return;
  if (el.tagName === "A") e.preventDefault();
  if (E.menuModelo && accion !== "menu-modelo" && accion !== "usar-modelo") E.menuModelo = false;
  const r = ACCIONES[accion]?.(el.dataset.valor);
  if (r?.catch) r.catch((err) => avisar(err.message));
});

document.addEventListener("toggle", (e) => {
  if (e.target.dataset?.accion === "ver-registro") pref.set("verRegistro", e.target.open);
}, true);

document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.campo) {
    const valor = t.type === "checkbox" ? t.checked : t.value;
    E.tc[t.dataset.campo] = valor;
    if (["idioma", "srt", "xlsx", "mmss"].includes(t.dataset.campo)) pref.set(t.dataset.campo, valor);
    if (t.dataset.campo === "idioma") dibujar(); // los avisos del modelo dependen del idioma
  } else if (t.dataset.campoLib) {
    E.lib[t.dataset.campoLib] = t.type === "checkbox" ? t.checked : t.value;
    if (t.dataset.campoLib === "texto") {
      const boton = document.querySelector('[data-accion="convertir"]');
      if (boton) boton.disabled = !t.value.trim();
    }
  } else if (t.dataset.col) {
    const i = Number(t.closest("tr").dataset.fila);
    E.lib.filas[i][t.dataset.col] = t.innerText.trim();
  }
});

// Al terminar de editar un PERSONAJE, se quita la marca de "por revisar" si ya no tiene '?'
document.addEventListener("focusout", (e) => {
  const t = e.target;
  if (t.dataset?.col === "personaje") {
    const tr = t.closest("tr");
    const fila = E.lib.filas[Number(tr.dataset.fila)];
    fila.revisar = !fila.personaje || fila.personaje.includes("?");
    tr.classList.toggle("revisar", fila.revisar);
  }
});

// Enter en una celda pasa a la de abajo (Shift+Enter hace salto de línea)
document.addEventListener("keydown", (e) => {
  const t = e.target;
  if (e.key === "Escape" && E.menuModelo) { E.menuModelo = false; dibujar(); }
  if (!t.dataset?.col || e.key !== "Enter" || e.shiftKey) return;
  e.preventDefault();
  const siguiente = t.closest("tr").nextElementSibling?.querySelector(`[data-col="${t.dataset.col}"]`);
  (siguiente || t).focus();
});

// ------------------------------------------------------------------
// Arranque
// ------------------------------------------------------------------

async function arrancar() {
  pintarIconos();
  for (let i = 0; i < 60 && !E.estado; i++) {
    try { await refrescarEstado(); } catch { await new Promise((r) => setTimeout(r, 400)); }
  }
  if (!E.estado) { $("#principal").innerHTML = '<div class="cargando-app">No se pudo conectar con la app. Ciérrala y vuelve a abrirla.</div>'; return; }
  if (!E.estado.modelos.some((m) => m.instalado)) E.vista = "modelos";
  dibujar();
  if (E.estado.cuda_instalacion.activo || E.estado.modelos.some((m) => m.descarga)) sondearDescargas();

  api("/api/actualizacion").then((a) => {
    if (!a.hay) return;
    const b = $("#actualizacion");
    b.hidden = false;
    b.querySelector("span").textContent = `Versión ${a.version} disponible`;
    b.onclick = () => ACCIONES.web(a.url);
  }).catch(() => {});
}

// En la ventana de escritorio, window.pywebview.api aparece un instante después de cargar
if (window.pywebview) arrancar();
else {
  let arrancado = false;
  const iniciar = () => { if (!arrancado) { arrancado = true; arrancar(); } };
  window.addEventListener("pywebviewready", iniciar);
  setTimeout(iniciar, 600);
}
