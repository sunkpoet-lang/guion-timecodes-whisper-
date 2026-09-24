// Guion con Time Codes — vista "Traducir" y la sección de modelos de traducción.
// Usa lo que define app.js (E, api, dibujar, icono, esc, ACCIONES, VISTAS…).

const VARIANTES = ["español latino neutro", "español de México", "español rioplatense (Argentina)",
  "español de Colombia", "español de Chile", "español de España"];

E.tr = {
  archivo: null, filas: null, formato: null, origen: null,   // guion a traducir
  perfiles: null, perfil: pref.get("perfil", null),
  editando: null, pestanaGlosario: "personajes", filtroGlosario: "",
  modelo: pref.get("modeloTraduccion", null), menuModelo: false,
  trabajo: null, datos: null, inicioTraduccion: null,
  soloRevisar: false, incluirOriginal: pref.get("incluirOriginal", false), nombre: "", carpeta: null, resultados: [],
};

const trEstado = () => E.estado.traduccion;
const trModelo = (id) => trEstado().modelos.find((m) => m.id === id);
const perfilActual = () => E.tr.perfiles?.find((p) => p.id === E.tr.perfil) || E.tr.perfiles?.[0] || null;

async function cargarPerfiles() {
  E.tr.perfiles = await api("/api/perfiles");
  if (!E.tr.perfiles.some((p) => p.id === E.tr.perfil)) E.tr.perfil = E.tr.perfiles[0]?.id || null;
}

function modeloTraduccionElegido() {
  const t = trEstado();
  const instalados = t.modelos.filter((m) => m.instalado);
  if (E.tr.modelo && instalados.some((m) => m.id === E.tr.modelo)) return E.tr.modelo;
  if (instalados.some((m) => m.id === t.recomendado)) return t.recomendado;
  return [...instalados].sort((a, b) => (b.veredicto === "ok") - (a.veredicto === "ok") || b.calidad - a.calidad)[0]?.id || null;
}

// ------------------------------------------------------------------
// Archivos que usa esta vista (los llama asignarArchivo de app.js)
// ------------------------------------------------------------------

window.tipoSoltadoTraducir = (ext) => {
  if (E.tr.editando) {
    if (ext === "xlsx") return "glosario";
    if (["md", "txt"].includes(ext)) return "estilo";
  }
  if (ext === "json") return "perfil";
  return ACEPTA.traducir.includes(ext) ? "traducir" : null;
};

window.asignarArchivoTraducir = (tipo, info) => {
  if (!["traducir", "glosario", "estilo", "perfil"].includes(tipo)) return false;
  if (!info || info.subiendo !== undefined) {
    if (tipo === "traducir") { E.tr.archivo = info; E.tr.filas = null; dibujar(); }
    return true;
  }
  ({ traducir: leerGuionATraducir, glosario: importarGlosario, estilo: importarEstilo, perfil: importarPerfil })[tipo](info)
    .catch((e) => avisar(e.message));
  return true;
};

async function leerGuionATraducir(info) {
  E.tr.archivo = info;
  E.tr.origen = info.ruta;
  E.tr.filas = null;
  dibujar();
  const r = await api("/api/libreto/convertir", { method: "POST", body: { ruta: info.ruta } });
  E.tr.filas = r.filas;
  E.tr.formato = r.formato;
  dibujar();
}

async function importarGlosario(info) {
  const g = await api("/api/perfiles/importar-glosario", { method: "POST", body: { ruta: info.ruta } });
  const glosario = E.tr.editando.glosario;
  // Las entradas nuevas reemplazan a las que tienen el mismo ORIGINAL
  for (const tipo of ["personajes", "terminos"]) {
    const nuevas = new Map(g[tipo].map((x) => [x.original.toLowerCase(), x]));
    glosario[tipo] = [...glosario[tipo].filter((x) => !nuevas.has(x.original.toLowerCase())), ...nuevas.values()];
  }
  dibujar();
  avisar(`Glosario importado: ${g.personajes.length} personajes y ${g.terminos.length} términos.`);
}

async function importarEstilo(info) {
  const r = await api("/api/perfiles/importar-estilo", { method: "POST", body: { ruta: info.ruta } });
  E.tr.editando.instrucciones = r.texto;
  if (/MAYÚSCULAS/.test(r.texto)) E.tr.editando.mayusculas = true;
  dibujar();
  avisar("Reglas de estilo importadas.");
}

async function importarPerfil(info) {
  const p = await api("/api/perfiles/importar", { method: "POST", body: { ruta: info.ruta } });
  await cargarPerfiles();
  E.tr.perfil = p.id;
  pref.set("perfil", p.id);
  dibujar();
  avisar(`Perfil «${p.nombre}» importado.`);
}

// ------------------------------------------------------------------
// Vista
// ------------------------------------------------------------------

VISTAS.traducir = () => {
  if (!E.tr.perfiles) {
    cargarPerfiles().then(dibujar).catch((e) => avisar(e.message));
    return '<div class="cargando-app"><span class="giro">' + icono("cargando", 22) + "</span></div>";
  }
  const d = E.tr.datos;
  const encabezado = `<div class="encabezado"><h1>Traducir guion</h1>
    <p>Traduce con un modelo que corre en tu equipo, sin internet, siguiendo las reglas y el glosario de cada traductor.
    El resultado es un borrador para revisar y adaptar.</p></div>`;
  if (d && d.estado === "corriendo") return encabezado + panelProgresoTraduccion(d);
  if (d && d.estado === "listo") return encabezado + panelResultadoTraduccion(d);
  if (d && d.estado === "error") {
    return encabezado + `<section class="seccion"><div class="aviso rojo">${icono("alerta", 18)}<div><b>No se pudo traducir.</b><br>${esc(d.error)}</div>
      <div class="acciones"><button class="boton" data-accion="tr-nueva">Volver</button></div></div>
      <div class="registro">${esc(d.log.join("\n"))}</div></section>`;
  }
  return encabezado + seccionGuion() + seccionPerfil() + seccionModeloTraduccion() + barraTraducir();
};

function seccionGuion() {
  let contenido;
  if (E.tr.archivo) {
    const meta = E.tr.archivo.subiendo !== undefined ? "Cargando…"
      : E.tr.filas ? `${E.tr.filas.length} líneas` + (E.tr.archivo.tamano ? ` · ${tamano(E.tr.archivo.tamano)}` : "") : "Leyendo…";
    contenido = `<div class="zona llena" data-tipo="traducir">
      <div class="zona-icono">${icono("documento", 20)}</div>
      <div class="zona-archivo"><div class="zona-nombre">${esc(E.tr.archivo.nombre)}</div><div class="zona-meta">${meta}</div></div>
      <button class="boton chico" data-accion="elegir" data-valor="traducir">Cambiar</button>
      <button class="boton-icono" data-accion="tr-quitar" title="Quitar">${icono("x", 16)}</button></div>`;
  } else {
    contenido = `<div class="zona" data-tipo="traducir" data-accion="elegir" data-valor="traducir">
      <div class="zona-icono">${icono("documento", 20)}</div>
      <div class="zona-titulo">Guion en el idioma original</div>
      <div class="zona-ayuda">Arrastra el archivo aquí o <u>búscalo</u></div>
      <div class="zona-ayuda">Word o Excel de 3 columnas (T.C. · PERSONAJE · DIÁLOGO), ASREC, .srt…</div></div>`;
  }
  return `<section class="seccion"><h2 class="seccion-titulo"><span class="paso-num">1</span>Guion</h2>
    <div class="archivos">${contenido}</div>
    <p class="ayuda" style="margin:10px 0 0">El T.C. y el orden de las líneas se conservan. La columna PERSONAJE se adapta con el glosario del perfil.</p>
  </section>`;
}

function resumenPerfil(p) {
  const g = p.glosario;
  const origen = IDIOMAS.find(([v]) => v === p.idioma_origen)?.[1] || p.idioma_origen;
  return [
    `<span class="etiqueta neutra">${esc(origen)} → ${esc(p.variante)}</span>`,
    `<span class="etiqueta neutra">${g.personajes.length} personajes · ${g.terminos.length} términos</span>`,
    p.acotacion ? `<span class="etiqueta neutra">paréntesis → ${esc(p.acotacion)}</span>` : "",
    p.mayusculas ? `<span class="etiqueta neutra">MAYÚSCULAS</span>` : "",
  ].join(" ");
}

function seccionPerfil() {
  if (E.tr.editando) return editorPerfil();
  const p = perfilActual();
  return `<section class="seccion">
    <h2 class="seccion-titulo"><span class="paso-num">2</span>Perfil de estilo
      <span class="extra"><a href="#" data-accion="elegir" data-valor="perfil">Importar perfil…</a></span></h2>
    <div class="fila-carpeta">
      <select class="entrada" data-tr="perfil">${E.tr.perfiles.map((x) =>
        `<option value="${esc(x.id)}" ${x.id === p?.id ? "selected" : ""}>${esc(x.nombre)}</option>`).join("")}</select>
      <button class="boton" data-accion="tr-editar">${icono("lapiz", 14)} Editar</button>
      <button class="boton" data-accion="tr-nuevo">${icono("mas", 14)} Nuevo</button>
    </div>
    ${p ? `<div style="margin-top:12px; display:flex; gap:6px; flex-wrap:wrap">${resumenPerfil(p)}</div>
      ${p.instrucciones ? `<details class="detalles"><summary>${icono("derecha", 13)}Ver reglas del perfil</summary>
        <div class="registro" style="font-family:inherit; font-size:12.5px">${esc(p.instrucciones)}</div></details>` : ""}` : ""}
  </section>`;
}

function editorPerfil() {
  const p = E.tr.editando;
  const g = p.glosario;
  const pestana = E.tr.pestanaGlosario;
  const filtro = E.tr.filtroGlosario.toLowerCase();
  const columnas = pestana === "personajes"
    ? [["original", "ORIGINAL"], ["doblaje", "DOBLAJE"], ["variantes", "VARIANTES (;)"], ["en_dialogo", "EN EL DIÁLOGO"]]
    : [["original", "ORIGINAL"], ["doblaje", "DOBLAJE"], ["notas", "NOTAS"]];
  const valor = (x, c) => (c === "variantes" ? (x.variantes || []).join("; ") : x[c] || "");
  const filas = g[pestana].map((x, i) => (filtro && !columnas.some(([c]) => valor(x, c).toLowerCase().includes(filtro))) ? "" :
    `<tr data-gfila="${i}">${columnas.map(([c]) =>
      `<td contenteditable="plaintext-only" data-gcol="${c}">${esc(valor(x, c))}</td>`).join("")}
      <td class="acc"><button class="boton-icono" data-accion="tr-glosario-borrar" data-valor="${i}" title="Borrar">${icono("basura", 15)}</button></td></tr>`).join("");

  return `<section class="seccion">
    <h2 class="seccion-titulo"><span class="paso-num">2</span>${p.id ? "Editar perfil" : "Nuevo perfil"}</h2>
    <div class="rejilla">
      <div class="campo"><label>Nombre del perfil</label><input class="entrada" data-pf="nombre" value="${esc(p.nombre)}" placeholder="Ej. Foot 2 Rue — Daniel"></div>
      <div class="campo"><label>Idioma del original</label><select class="entrada" data-pf="idioma_origen">${IDIOMAS.map(([v, t]) =>
        `<option value="${v}" ${p.idioma_origen === v ? "selected" : ""}>${t}</option>`).join("")}</select></div>
      <div class="campo"><label>Traducir a</label><input class="entrada" data-pf="variante" value="${esc(p.variante)}" list="variantes">
        <datalist id="variantes">${VARIANTES.map((v) => `<option value="${esc(v)}">`).join("")}</datalist></div>
      <div class="campo"><label>Unificar acotaciones entre paréntesis</label>
        <input class="entrada" data-pf="acotacion" value="${esc(p.acotacion)}" placeholder="Vacío = se traducen. Ej. (REAC)">
        <span class="ayuda">Si lo llenas, todo paréntesis del diálogo traducido se reemplaza por esto.</span></div>
      <label class="interruptor"><input type="checkbox" data-pf="mayusculas" ${p.mayusculas ? "checked" : ""}><span class="pista"></span>
        <span class="interruptor-texto"><b>Entregar en MAYÚSCULAS</b><span>Convención de rayado. Se aplica al final a toda la traducción.</span></span></label>
      <div class="campo ancho"><label style="display:flex; align-items:center">Reglas de estilo del traductor
          <a href="#" style="margin-left:auto; font-weight:500" data-accion="elegir" data-valor="estilo">Importar de un archivo (.md / .txt)…</a></label>
        <textarea class="entrada" data-pf="instrucciones" style="min-height:170px; font-family:inherit; font-size:13px"
          placeholder="Escribe las reglas como se las explicarías a otro traductor: registro, tú o usted, palabras prohibidas, cómo tratar interjecciones, juegos de palabras…">${esc(p.instrucciones)}</textarea></div>
    </div>

    <h3 class="seccion-titulo" style="margin-top:22px">Glosario
      <span class="extra"><a href="#" data-accion="elegir" data-valor="glosario">Importar de Excel (.xlsx)…</a></span></h3>
    <div class="tabla-marco">
      <div class="tabla-herramientas">
        <div class="segmentado" style="padding:2px">
          <button class="${pestana === "personajes" ? "activo" : ""}" data-accion="tr-glosario-pestana" data-valor="personajes">Personajes (${g.personajes.length})</button>
          <button class="${pestana === "terminos" ? "activo" : ""}" data-accion="tr-glosario-pestana" data-valor="terminos">Términos (${g.terminos.length})</button>
        </div>
        <input class="entrada" style="max-width:220px; padding:6px 10px" data-tr="filtroGlosario" value="${esc(E.tr.filtroGlosario)}" placeholder="Buscar…">
        <button class="boton chico fantasma" style="margin-left:auto" data-accion="tr-glosario-mas">${icono("mas", 14)} Agregar</button>
      </div>
      <div class="tabla-scroll" style="max-height:320px"><table class="libreto glosario">
        <thead><tr>${columnas.map(([, t]) => `<th>${t}</th>`).join("")}<th></th></tr></thead>
        <tbody>${filas || `<tr><td colspan="5" class="vacio">Sin entradas. Agrégalas o importa un glosario de Excel (pestañas PERSONAJES y TERMINOS, o columnas ORIGINAL y DOBLAJE).</td></tr>`}</tbody>
      </table></div>
    </div>

    <div style="display:flex; gap:10px; margin-top:18px">
      <button class="boton primario" data-accion="tr-guardar">${icono("check", 15)} Guardar perfil</button>
      <button class="boton" data-accion="tr-cancelar-edicion">Cancelar</button>
      ${p.id ? `<button class="boton fantasma" data-accion="tr-exportar-perfil">${icono("subir", 14)} Exportar para compartir</button>
        <button class="boton fantasma peligro" style="margin-left:auto" data-accion="tr-borrar-perfil">${icono("basura", 14)} Borrar perfil</button>` : ""}
    </div>
  </section>`;
}

function seccionModeloTraduccion() {
  const t = trEstado();
  const id = modeloTraduccionElegido();
  const m = trModelo(id);
  let contenido;
  if (!t.motor.instalado) {
    const j = t.instalacion_motor;
    contenido = j.activo
      ? `<div class="aviso info">${icono("descarga", 17)}<div style="flex:1"><b>${esc(j.etapa)}</b>
          <div class="barra" style="margin-top:8px"><i style="width:${j.total ? j.hechos / j.total * 100 : 5}%"></i></div></div></div>`
      : `<div class="aviso amarillo">${icono("info", 17)}<div>Para traducir hace falta el motor <b>llama.cpp</b> (unos 30 MB, de su página oficial). Se instala una sola vez.
          ${j.error ? `<br><span style="color:var(--error)">${esc(j.error)}</span>` : ""}</div>
          <div class="acciones"><button class="boton chico primario" data-accion="motor-instalar">Instalar motor</button></div></div>`;
  } else if (!m) {
    const r = trModelo(t.recomendado);
    contenido = `<div class="aviso amarillo">${icono("info", 17)}<div>No hay modelos de traducción descargados. Para tu equipo recomendamos <b>${r.nombre}</b> (${tamanoMB(r.tamano_mb)}).</div>
      <div class="acciones"><button class="boton chico primario" data-accion="trmodelo-descargar-ir" data-valor="${r.id}">Descargarlo</button></div></div>`;
  } else {
    const menu = E.tr.menuModelo ? `<div class="menu-modelos">${t.modelos.filter((x) => x.instalado).map((x) => `
        <button class="opcion-modelo ${x.id === id ? "activo" : ""}" data-accion="tr-usar-modelo" data-valor="${x.id}">
          <div><div style="font-weight:600">${x.nombre} ${x.id === t.recomendado ? `<span class="etiqueta acento">${icono("estrella", 11)} Recomendado</span>` : ""}</div>
            <div class="ayuda">${esc(x.nota)}</div></div>
          <div class="der">${minutos(x.minutos)}<br><span>en ${x.dispositivo === "gpu" ? "GPU" : "procesador"}</span></div>
        </button>`).join("")}
        <div class="separador"></div>
        <button class="opcion-modelo mas" data-accion="ir" data-valor="modelos">${icono("descarga", 16)} Descargar otros modelos…</button></div>` : "";
    const recomendadoFalta = t.recomendado !== id && !trModelo(t.recomendado).instalado;
    contenido = `<div style="position:relative">
      <button class="modelo-elegido" data-accion="tr-menu-modelo">
        <div><div class="nombre">${m.nombre} ${id === t.recomendado ? `<span class="etiqueta acento">${icono("estrella", 11)} Recomendado para tu equipo</span>` : ""}</div>
          <div class="detalle">En ${m.dispositivo === "gpu" ? "GPU" : "procesador"} · ${minutos(m.minutos)} por episodio de 22 min</div></div>
        <span class="chevron">${icono("abajo", 16)}</span></button>${menu}</div>
      ${recomendadoFalta ? `<span class="ayuda">Para tu equipo recomendamos <b>${trModelo(t.recomendado).nombre}</b>. <a href="#" data-accion="trmodelo-descargar-ir" data-valor="${t.recomendado}">Descargarlo</a></span>` : ""}
      ${m.veredicto === "lento" ? `<div class="aviso amarillo" style="margin-top:10px">${icono("reloj", 17)}<div>En este equipo, ${m.nombre} tarda ${minutos(m.minutos)} por episodio.</div></div>` : ""}`;
  }
  return `<section class="seccion"><h2 class="seccion-titulo"><span class="paso-num">3</span>Modelo de traducción</h2>${contenido}</section>`;
}

function faltantesTraduccion() {
  const f = [];
  if (!E.tr.filas) f.push(E.tr.archivo ? "que termine de leer el guion" : "el guion");
  if (E.tr.editando) f.push("guardar el perfil");
  if (!trEstado().motor.instalado) f.push("instalar el motor");
  else if (!modeloTraduccionElegido()) f.push("un modelo de traducción");
  return f;
}

function barraTraducir() {
  const f = faltantesTraduccion();
  const m = trModelo(modeloTraduccionElegido());
  const resumen = f.length ? `<span class="falta">Falta ${f.join(" y ")}.</span>`
    : `<b>${E.tr.filas.length} líneas</b> con el perfil <b>${esc(perfilActual().nombre)}</b> · ${m.nombre}`;
  return `<div class="barra-accion"><div class="resumen">${resumen}</div>
    <button class="boton primario grande" data-accion="tr-traducir" ${f.length ? "disabled" : ""}>${icono("idiomas", 17)} Traducir</button></div>`;
}

function panelProgresoTraduccion(d) {
  const pct = Math.round((d.progreso || 0) * 100);
  let restante = "";
  if (d.hechas && E.tr.inicioTraduccion && d.hechas > E.tr.inicioTraduccion.hechas) {
    const seg = Date.now() / 1000 - E.tr.inicioTraduccion.t;
    const velocidad = (d.hechas - E.tr.inicioTraduccion.hechas) / seg;
    restante = ` · quedan ≈ ${reloj((d.total - d.hechas) / velocidad)}`;
  }
  const ultimas = (d.filas || []).filter((f) => f.traduccion).slice(-6);
  return `<section class="seccion progreso-panel">
    <div class="progreso-cabecera"><span class="giro">${icono("cargando", 22)}</span>
      <div><h2>${esc(d.etapa)}…</h2><div class="tiempo">${d.total ? `${d.hechas} de ${d.total} líneas · ` : ""}${reloj(d.transcurrido)} transcurrido${restante}</div></div>
      <button class="boton peligro" style="margin-left:auto" data-accion="tr-cancelar">${icono("parar", 14)} Cancelar</button></div>
    <div class="barra ${d.total ? "" : "indeterminada"}"><i style="width:${pct}%"></i></div>
    ${d.etapa === "Cargando modelo" ? `<p class="ayuda" style="margin:12px 0 0">La primera vez tarda un poco más: el modelo se carga en memoria y la GPU prepara sus rutinas.</p>` : ""}
    ${ultimas.length ? `<div class="tabla-marco" style="margin-top:16px"><table class="libreto"><tbody>${ultimas.map((f) => `
      <tr><td class="pj" style="padding:8px 10px">${esc(f.personaje)}</td><td style="padding:8px 10px; color:var(--texto-3)">${esc(f.original)}</td>
      <td style="padding:8px 10px">${esc(f.traduccion)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    <details class="detalles"><summary>${icono("derecha", 13)}Ver registro</summary><div class="registro">${esc(d.log.join("\n"))}</div></details>
  </section>`;
}

function panelResultadoTraduccion(d) {
  const filas = d.filas;
  const revisar = filas.filter((f) => f.revisar).length;
  const faltan = Object.entries(d.sin_glosario || {}).sort((a, b) => b[1] - a[1]);
  const base = E.tr.archivo ? nombreBase(E.tr.archivo.nombre) : "guion";
  const cuerpo = filas.map((f, i) => (E.tr.soloRevisar && !f.revisar) ? "" : `
    <tr class="${f.revisar ? "revisar" : ""}" data-fila="${i}">
      <td class="num">${i + 1}</td>
      <td class="tc">${esc(f.timecode)}</td>
      <td class="pj" contenteditable="plaintext-only" data-tcol="personaje">${esc(f.personaje)}</td>
      <td style="padding:8px 10px; color:var(--texto-3); width:36%">${esc(f.original)}</td>
      <td contenteditable="plaintext-only" data-tcol="dialogo">${esc(f.dialogo)}</td>
    </tr>${f.avisos.length ? `<tr class="revisar aviso-fila"><td></td><td colspan="4" class="ayuda" style="padding:0 10px 8px; color:var(--aviso)">${f.avisos.map(esc).join(" · ")}</td></tr>` : ""}`).join("");

  return `<section class="seccion">
    <div class="resultado-cabecera"><div class="resultado-icono">${icono("check", 22, 2.5)}</div>
      <div><h2>Traducción lista</h2><p>${filas.length} líneas en ${reloj(d.transcurrido)}. Revisa y corrige en la tabla antes de exportar.</p></div>
      <button class="boton" style="margin-left:auto" data-accion="tr-nueva">${icono("reintentar", 14)} Nueva traducción</button></div>
    ${faltan.length ? `<div class="aviso amarillo" style="margin-bottom:14px">${icono("alerta", 17)}<div>
      <b>Personajes que no están en el glosario</b> (quedaron sin adaptar en la columna PERSONAJE):
      ${faltan.slice(0, 12).map(([n, c]) => `${esc(n)} (${c})`).join(", ")}${faltan.length > 12 ? "…" : ""}</div>
      <div class="acciones"><button class="boton chico" data-accion="tr-agregar-faltantes">Agregar al glosario</button></div></div>` : ""}
    <div class="tabla-marco">
      <div class="tabla-herramientas">
        <span>${filas.length} líneas</span>
        ${revisar ? `<button class="boton chico ${E.tr.soloRevisar ? "primario" : ""}" data-accion="tr-solo-revisar">${icono("filtro", 13)} ${revisar} por revisar</button>`
          : `<span class="etiqueta ok">${icono("check", 12)} Glosario respetado</span>`}
        <span class="ayuda" style="margin-left:auto">Haz clic en la traducción o en PERSONAJE para corregir</span>
      </div>
      <div class="tabla-scroll" style="max-height:560px"><table class="libreto">
        <thead><tr><th></th><th>T.C.</th><th>PERSONAJE</th><th>ORIGINAL</th><th>TRADUCCIÓN</th></tr></thead>
        <tbody>${cuerpo}</tbody></table></div>
    </div>
  </section>
  <section class="seccion">
    <h2 class="seccion-titulo">Exportar</h2>
    <div class="rejilla">
      <div class="campo"><label>Nombre del archivo</label>
        <input class="entrada" data-tr="nombre" value="${esc(E.tr.nombre)}" placeholder="${esc(base)}_ES" spellcheck="false">
        <span class="ayuda">La extensión (.docx o .xlsx) se pone sola.</span></div>
      ${escritorio() ? `<div class="campo"><span class="rotulo">Guardar en</span><div class="fila-carpeta">
        <div class="entrada">${E.tr.carpeta ? esc(E.tr.carpeta) : E.tr.origen ? "La misma carpeta del guion" : "Carpeta de salidas de la app"}</div>
        <button class="boton" data-accion="tr-carpeta">${icono("carpeta", 15)} Cambiar</button></div></div>` : ""}
      <label class="interruptor"><input type="checkbox" data-tr="incluirOriginal" ${E.tr.incluirOriginal ? "checked" : ""}><span class="pista"></span>
        <span class="interruptor-texto"><b>Incluir la columna ORIGINAL</b><span>Para revisar. Sin ella salen las 3 columnas: T.C. · PERSONAJE · DIÁLOGO.</span></span></label>
    </div>
    <div style="display:flex; gap:10px; margin-top:18px">
      <button class="boton primario grande" data-accion="tr-exportar" data-valor="docx">${icono("documento", 17)} Exportar a Word</button>
      <button class="boton grande" data-accion="tr-exportar" data-valor="xlsx">${icono("hoja", 17)} Exportar a Excel</button>
    </div>
    ${E.tr.resultados.length ? `<div style="margin-top:14px">${E.tr.resultados.map((r) => filaArchivoSalida(r)).join("")}</div>` : ""}
  </section>`;
}

// ------------------------------------------------------------------
// Sección de "Modelos y equipo"
// ------------------------------------------------------------------

function velocidadTraduccion(minutosEpisodio) {
  return minutosEpisodio < 3 ? 5 : minutosEpisodio < 6 ? 4 : minutosEpisodio < 12 ? 3 : minutosEpisodio < 25 ? 2 : 1;
}

window.seccionModelosTraduccion = () => {
  const t = trEstado();
  const j = t.instalacion_motor;
  let motor;
  if (j.activo) {
    motor = `<div class="aviso info">${icono("descarga", 17)}<div style="flex:1"><b>${esc(j.etapa)}</b>
      <div class="barra" style="margin-top:8px"><i style="width:${j.total ? j.hechos / j.total * 100 : 5}%"></i></div></div></div>`;
  } else if (!t.motor.instalado) {
    motor = `<div class="aviso amarillo">${icono("info", 17)}<div>Hace falta el motor <b>llama.cpp</b> (unos 30 MB, de su página oficial en GitHub).
      Acelera con GPUs NVIDIA, AMD e Intel${E.estado.hardware.apple_silicon ? " y con Metal en Mac" : ""}, o usa el procesador.
      ${j.error ? `<br><span style="color:var(--error)">${esc(j.error)}</span>` : ""}</div>
      <div class="acciones"><button class="boton primario" data-accion="motor-instalar">Instalar motor</button></div></div>`;
  } else {
    motor = `<div class="aviso verde">${icono("rayo", 17)}<div><b>Motor listo</b> (llama.cpp ${esc(t.motor.version)}).
      ${t.motor.gpu ? `Acelera con ${esc(t.motor.gpu.nombre)} (${t.motor.gpu.vram_gb} GB).` : "No encontró una GPU compatible: usará el procesador."}</div>
      <div class="acciones"><button class="boton chico fantasma" data-accion="motor-borrar">Quitar</button></div></div>`;
  }

  const tarjetas = t.modelos.map((m) => {
    const insignias = [
      m.id === t.recomendado ? `<span class="etiqueta acento">${icono("estrella", 11)} Recomendado</span>` : "",
      m.instalado ? `<span class="etiqueta ok">${icono("check", 11, 3)} Instalado</span>` : "",
    ].join("");
    const estimado = m.veredicto === "no_cabe" ? `<span class="etiqueta aviso">Poca memoria para este modelo</span>`
      : `<span ${m.veredicto === "lento" ? 'style="color:var(--aviso)"' : ""}>${minutos(m.minutos)} por episodio<br>en ${m.dispositivo === "gpu" ? "GPU" : "procesador"}${m.veredicto === "lento" ? " (lento)" : ""}</span>`;
    let accion;
    if (m.descarga && !m.descarga.error) {
      const pct = m.descarga.total ? m.descarga.hechos / m.descarga.total * 100 : 0;
      accion = `<div class="progreso-mini"><div class="barra"><i style="width:${pct}%"></i></div>
        <div class="texto"><span>${tamano(m.descarga.hechos)} / ${tamano(m.descarga.total)}</span>
        <a href="#" data-accion="trmodelo-cancelar" data-valor="${m.id}">Cancelar</a></div></div>`;
    } else if (m.descarga?.error) {
      accion = `<span class="etiqueta error" title="${esc(m.descarga.error)}">Error al descargar</span>
        <button class="boton chico" data-accion="trmodelo-descargar" data-valor="${m.id}">${icono("reintentar", 13)} Reintentar</button>`;
    } else if (m.instalado) {
      accion = `<div style="display:flex; gap:6px"><button class="boton chico" data-accion="trmodelo-usar" data-valor="${m.id}">Usar</button>
        <button class="boton-icono" data-accion="trmodelo-borrar" data-valor="${m.id}" title="Borrar del disco">${icono("basura", 15)}</button></div>`;
    } else {
      accion = `<button class="boton chico ${m.id === t.recomendado ? "primario" : ""}" data-accion="trmodelo-descargar" data-valor="${m.id}">${icono("descarga", 14)} Descargar · ${tamanoMB(m.tamano_mb)}</button>`;
    }
    return `<div class="tarjeta-modelo ${m.id === t.recomendado ? "recomendado" : ""}">
      <div><div class="titulo">${m.nombre} ${insignias}</div><div class="nota">${esc(m.nota)}</div>
        <div class="meta"><span>${tamanoMB(m.tamano_mb)}</span><span>Apache 2.0</span>
          <a href="#" data-accion="web" data-valor="${esc(m.url)}">Ver en Hugging Face ↗</a></div></div>
      <div class="medidores"><span>Calidad</span>${medidor(m.calidad)}<span>Velocidad</span>${medidor(velocidadTraduccion(m.minutos))}</div>
      <div class="lado"><div class="estimado">${estimado}</div>${accion}</div></div>`;
  }).join("");

  return `<section class="seccion">
    <h2 class="seccion-titulo">Modelos de traducción<span class="extra">Corren en tu equipo, sin internet · tiempos para un episodio de 22 min</span></h2>
    ${motor}
    <div class="lista-modelos" style="margin-top:14px">${tarjetas}</div>
  </section>`;
};

// ------------------------------------------------------------------
// Traducción en curso
// ------------------------------------------------------------------

async function iniciarTraduccion() {
  try {
    const cuerpo = { perfil: perfilActual().id, modelo: modeloTraduccionElegido() };
    if (E.tr.archivo?.ruta) cuerpo.ruta = E.tr.archivo.ruta; else cuerpo.filas = E.tr.filas;
    const { id } = await api("/api/traducir", { method: "POST", body: cuerpo });
    Object.assign(E.tr, { trabajo: id, inicioTraduccion: null, resultados: [], soloRevisar: false,
      datos: { estado: "corriendo", etapa: "Iniciando", progreso: 0, hechas: 0, total: 0, filas: [], log: [], transcurrido: 0 } });
    dibujar();
    seguirTraduccion();
  } catch (e) { avisar(e.message); }
}

async function seguirTraduccion() {
  while (E.tr.trabajo) {
    try {
      const d = await api(`/api/trabajos/${E.tr.trabajo}`);
      if (d.etapa === "Traduciendo" && !E.tr.inicioTraduccion) E.tr.inicioTraduccion = { t: Date.now() / 1000, hechas: d.hechas };
      E.tr.datos = d;
      if (d.estado !== "corriendo") {
        E.tr.trabajo = null;
        if (d.estado === "cancelado") { E.tr.datos = null; avisar("Traducción cancelada."); }
        else if (d.estado === "listo" && E.vista !== "traducir") avisar("Traducción lista.");
      }
      if (E.vista === "traducir") dibujar(); else dibujarLateral();
    } catch { /* reintenta */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

async function exportarTraduccion(tipo) {
  const base = E.tr.archivo ? nombreBase(E.tr.archivo.nombre) : "guion";
  try {
    const r = await api("/api/libreto/exportar", {
      method: "POST",
      body: { filas: E.tr.datos.filas, nombre: E.tr.nombre || `${base}_ES`, tipo, incluir_original: E.tr.incluirOriginal,
        carpeta: E.tr.carpeta, origen: E.tr.origen },
    });
    E.tr.resultados = [r, ...E.tr.resultados.filter((x) => x.ruta !== r.ruta)];
    dibujar();
    avisar(`${tipo === "xlsx" ? "Excel" : "Word"} generado (${r.lineas} líneas).`);
  } catch (e) { avisar(e.message); }
}

// ------------------------------------------------------------------
// Acciones y eventos
// ------------------------------------------------------------------

const nuevoPerfil = () => ({ id: null, nombre: "", idioma_origen: "en", variante: "español latino neutro", instrucciones: "",
  acotacion: "", mayusculas: false, glosario: { personajes: [], terminos: [] } });

async function refrescarYSondear() { await refrescarEstado(); dibujar(); sondearDescargas(); }

Object.assign(ACCIONES, {
  async "traducir-archivo"(ruta) {
    E.vista = "traducir";
    E.tr.datos = null;
    await leerGuionATraducir(await api("/api/archivo", { method: "POST", body: { ruta } }));
  },
  "traducir-tabla"() {
    const L = E.lib;
    Object.assign(E.tr, { filas: L.filas.map((f) => ({ ...f })), formato: L.formato, datos: null,
      archivo: { nombre: L.pestana === "archivo" && L.archivo ? L.archivo.nombre : "Tabla de Convertir libreto" },
      origen: L.pestana === "archivo" ? L.archivo?.ruta : null });
    E.vista = "traducir";
    dibujar();
  },
  "tr-quitar"() { Object.assign(E.tr, { archivo: null, filas: null, origen: null }); dibujar(); },
  "tr-editar"() { E.tr.editando = JSON.parse(JSON.stringify(perfilActual())); E.tr.filtroGlosario = ""; dibujar(); },
  "tr-nuevo"() { E.tr.editando = nuevoPerfil(); dibujar(); },
  "tr-cancelar-edicion"() { E.tr.editando = null; dibujar(); },
  async "tr-guardar"() {
    const p = await api("/api/perfiles", { method: "POST", body: E.tr.editando });
    await cargarPerfiles();
    Object.assign(E.tr, { perfil: p.id, editando: null });
    pref.set("perfil", p.id);
    dibujar();
    avisar("Perfil guardado.");
  },
  async "tr-borrar-perfil"() {
    if (!confirm(`¿Borrar el perfil «${E.tr.editando.nombre}»? Se pierden sus reglas y su glosario.`)) return;
    await api(`/api/perfiles/${E.tr.editando.id}`, { method: "DELETE" });
    E.tr.editando = null;
    await cargarPerfiles();
    dibujar();
  },
  async "tr-exportar-perfil"() {
    const carpeta = escritorio() ? await window.pywebview.api.elegir_carpeta() : null;
    if (escritorio() && !carpeta) return;
    const r = await api(`/api/perfiles/${E.tr.editando.id}/exportar`, { method: "POST", body: { carpeta } });
    if (escritorio()) await api("/api/abrir", { method: "POST", body: { ruta: r.ruta, carpeta: true } });
    else location.href = `/api/descargar?t=${TOKEN}&ruta=${encodeURIComponent(r.ruta)}`;
    avisar("Perfil exportado. Compártelo con otros traductores; lo importan desde «Importar perfil».");
  },
  "tr-glosario-pestana"(v) { E.tr.pestanaGlosario = v; dibujar(); },
  "tr-glosario-mas"() {
    const nueva = E.tr.pestanaGlosario === "personajes"
      ? { original: "", doblaje: "", variantes: [], en_dialogo: "", tipo: "personaje", notas: "" }
      : { original: "", doblaje: "", notas: "" };
    E.tr.editando.glosario[E.tr.pestanaGlosario].unshift(nueva);
    E.tr.filtroGlosario = "";
    dibujar();
    document.querySelector('[data-gfila="0"] td')?.focus();
  },
  "tr-glosario-borrar"(i) { E.tr.editando.glosario[E.tr.pestanaGlosario].splice(Number(i), 1); dibujar(); },
  "tr-menu-modelo"() { E.tr.menuModelo = !E.tr.menuModelo; dibujar(); },
  "tr-usar-modelo"(v) { E.tr.modelo = v; pref.set("modeloTraduccion", v); E.tr.menuModelo = false; dibujar(); },
  "tr-traducir": iniciarTraduccion,
  async "tr-cancelar"() { if (E.tr.trabajo && confirm("¿Cancelar la traducción?")) await api(`/api/trabajos/${E.tr.trabajo}/cancelar`, { method: "POST" }); },
  "tr-nueva"() { Object.assign(E.tr, { datos: null, trabajo: null, resultados: [], nombre: "" }); dibujar(); },
  "tr-solo-revisar"() { E.tr.soloRevisar = !E.tr.soloRevisar; dibujar(); },
  "tr-exportar": exportarTraduccion,
  async "tr-carpeta"() { const c = await window.pywebview.api.elegir_carpeta(); if (c) { E.tr.carpeta = c; dibujar(); } },
  "tr-agregar-faltantes"() {
    const perfil = JSON.parse(JSON.stringify(perfilActual()));
    for (const nombre of Object.keys(E.tr.datos.sin_glosario || {})) {
      perfil.glosario.personajes.unshift({ original: nombre, doblaje: "", variantes: [], en_dialogo: "", tipo: "personaje", notas: "" });
    }
    Object.assign(E.tr, { editando: perfil, pestanaGlosario: "personajes", filtroGlosario: "", datos: null, trabajo: null });
    dibujar();
    avisar("Completa la columna DOBLAJE, guarda el perfil y vuelve a traducir.");
  },
  async "motor-instalar"() { await api("/api/motor/instalar", { method: "POST" }); await refrescarYSondear(); },
  async "motor-borrar"() {
    if (!confirm("¿Quitar el motor de traducción? Los modelos descargados se conservan.")) return;
    await api("/api/motor", { method: "DELETE" }); await refrescarEstado(); dibujar();
  },
  async "trmodelo-descargar"(v) { await api(`/api/traduccion/modelos/${v}/descargar`, { method: "POST" }); await refrescarYSondear(); },
  async "trmodelo-descargar-ir"(v) {
    if (!trEstado().motor.instalado) await api("/api/motor/instalar", { method: "POST" });
    await api(`/api/traduccion/modelos/${v}/descargar`, { method: "POST" });
    E.vista = "modelos";
    await refrescarYSondear();
  },
  async "trmodelo-cancelar"(v) { await api(`/api/traduccion/modelos/${v}/cancelar`, { method: "POST" }); },
  async "trmodelo-borrar"(v) {
    const m = trModelo(v);
    if (!confirm(`¿Borrar ${m.nombre} del disco? Libera ${tamanoMB(m.tamano_mb)}.`)) return;
    await api(`/api/traduccion/modelos/${v}`, { method: "DELETE" }).catch((e) => avisar(e.message));
    await refrescarEstado(); dibujar();
  },
  "trmodelo-usar"(v) { E.tr.modelo = v; pref.set("modeloTraduccion", v); E.vista = "traducir"; dibujar(); avisar(`Se usará ${trModelo(v).nombre}.`); },
});

document.addEventListener("click", (e) => {
  if (E.tr.menuModelo && !e.target.closest(".menu-modelos") && !e.target.closest('[data-accion="tr-menu-modelo"]')) {
    E.tr.menuModelo = false;
    dibujar();
  }
});

document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.tr) {
    const valor = t.type === "checkbox" ? t.checked : t.value;
    E.tr[t.dataset.tr] = valor;
    if (t.dataset.tr === "perfil") { pref.set("perfil", valor); dibujar(); }
    if (t.dataset.tr === "incluirOriginal") pref.set("incluirOriginal", valor);
    if (t.dataset.tr === "filtroGlosario") {
      dibujar();
      const campo = document.querySelector('[data-tr="filtroGlosario"]');
      campo?.focus();
      campo?.setSelectionRange(campo.value.length, campo.value.length);
    }
  } else if (t.dataset.pf) {
    E.tr.editando[t.dataset.pf] = t.type === "checkbox" ? t.checked : t.value;
  } else if (t.dataset.gcol) {
    const entrada = E.tr.editando.glosario[E.tr.pestanaGlosario][Number(t.closest("tr").dataset.gfila)];
    const texto = t.innerText.trim();
    entrada[t.dataset.gcol] = t.dataset.gcol === "variantes" ? texto.split(";").map((x) => x.trim()).filter(Boolean) : texto;
  } else if (t.dataset.tcol) {
    E.tr.datos.filas[Number(t.closest("tr").dataset.fila)][t.dataset.tcol] = t.innerText.trim();
  }
});

// Enter en una celda de la traducción pasa a la de abajo (Shift+Enter hace salto de línea)
document.addEventListener("keydown", (e) => {
  const t = e.target;
  if (!t.dataset?.tcol || e.key !== "Enter" || e.shiftKey) return;
  e.preventDefault();
  let fila = t.closest("tr").nextElementSibling;
  while (fila && !fila.dataset.fila) fila = fila.nextElementSibling;
  (fila?.querySelector(`[data-tcol="${t.dataset.tcol}"]`) || t).focus();
});
