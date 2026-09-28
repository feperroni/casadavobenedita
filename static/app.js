const CARGOS = ["Médium Fixo", "Médium de Rodízio", "Cambono"];
const AREAS = ["Mediunidade", "Liderança", "Curimba"];
// Espelha TipoGiraEnum em app/models.py
const LINHAS = ["Preto Velho", "Caboclo", "Exu", "Pomba Gira", "Erê", "Mirim",
  "Baiano", "Malandro", "Marinheiro", "Cigano", "Boiadeiro", "Orixá", "Outro"];
const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
// Espelha FuncaoOperacionalEnum em app/models.py — a Limpeza 2 é feita por
// duas pessoas e por isso ocupa duas posições no rodízio.
const FUNCOES = ["Porteira de Atendimento", "Porteira de Senha", "Limpeza 1",
  "Limpeza 2 - Pessoa 1", "Limpeza 2 - Pessoa 2"];
// As duas posições da Limpeza 2 são o mesmo trabalho: uma caixa só no
// cadastro, cobrindo as duas (espelha FUNCOES_COM_APTIDAO em app/models.py).
const FUNCOES_COM_APTIDAO = FUNCOES.filter((f) => f !== "Limpeza 2 - Pessoa 2");
const ROTULO_APTIDAO = { "Limpeza 2 - Pessoa 1": "Limpeza 2 (as duas posições)" };
// Só estes cargos entram no rodízio das funções operacionais (ver services/funcoes.py)
const CARGOS_FUNCAO = ["Médium de Rodízio", "Cambono"];

const estado = {
  pessoas: [],
  entidades: [],
  pagamentos: [],
  itensEstoque: [],
  integranteSelecionado: null,
  espiritualSelecionado: null,
  destinatarios: [],
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const ENTIDADES_HTML = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (valor) => String(valor ?? "").replace(/[&<>"']/g, (c) => ENTIDADES_HTML[c]);

function avisar(texto) {
  const aviso = $("#aviso");
  aviso.textContent = texto;
  aviso.classList.add("visivel");
  setTimeout(() => aviso.classList.remove("visivel"), 3200);
}

async function api(metodo, caminho, corpo) {
  const resposta = await fetch(caminho, {
    method: metodo,
    headers: corpo ? { "Content-Type": "application/json" } : undefined,
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  if (!resposta.ok) {
    let detalhe = `Erro ${resposta.status}`;
    try {
      const json = await resposta.json();
      if (json.detail) detalhe = typeof json.detail === "string" ? json.detail : detalhe;
    } catch (e) { /* resposta sem JSON */ }
    throw new Error(detalhe);
  }
  return resposta.status === 204 ? null : resposta.json();
}

const moeda = (valor) =>
  (valor || 0).toLocaleString("pt-br", { style: "currency", currency: "BRL" });

const dataCurta = (iso) => new Date(iso).toLocaleDateString("pt-br");

function preencherSelect(select, valores) {
  select.innerHTML = valores
    .map((v) => `<option value="${v.valor ?? v}">${v.rotulo ?? v}</option>`)
    .join("");
}

// ---------------- Navegação ----------------
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".view").forEach((v) => v.classList.remove("active"));
    tab.classList.add("active");
    $(`#view-${tab.dataset.view}`).classList.add("active");
    if (tab.dataset.view === "financeiro") carregarFinanceiro();
    if (tab.dataset.view === "espiritual") carregarEspiritual();
    if (tab.dataset.view === "geral") carregarVisaoGeral();
    if (tab.dataset.view === "estoque") carregarEstoque();
  });
});

function irParaAba(nome) {
  $(`.tab[data-view="${nome}"]`).click();
}

$$("[data-fechar]").forEach((btn) =>
  btn.addEventListener("click", () => btn.closest(".modal").classList.remove("aberto"))
);

// ---------------- Visão geral ----------------
async function carregarVisaoGeral() {
  const [resumo, pessoas] = await Promise.all([
    api("GET", "/dashboard/visao-geral"),
    api("GET", "/pessoas/"),
  ]);
  estado.pessoas = pessoas;

  $("#kpi-mediuns").textContent = resumo.total_mediunidade;
  $("#kpi-lideranca").textContent = resumo.total_lideranca;
  $("#kpi-curimba").textContent = resumo.total_curimba;
  $("#kpi-integrantes").textContent = resumo.total_integrantes;
  $("#kpi-giras").textContent = resumo.total_giras;
  $("#kpi-atenderam").textContent = resumo.mediuns_que_atenderam;
  $("#kpi-entidades").textContent = resumo.total_entidades;

  renderizarGiras(resumo.ultimas_giras);
  renderizarIntegrantes();
}

function renderizarGiras(giras) {
  $("#tabela-giras").innerHTML = giras.length
    ? giras.map((g) => `
        <tr data-gira="${g.gira_id}">
          <td>${dataCurta(g.data)}</td>
          <td>${esc(g.nome) || "—"}</td>
          <td>${g.tipo}</td>
          <td>${g.escalados}</td>
          <td>${g.presentes}</td>
          <td class="acoes">
            <button class="btn btn-editar-gira">Editar</button>
            <button class="btn btn-perigo btn-remover-gira">Remover</button>
          </td>
        </tr>`).join("")
    : `<tr><td colspan="6" class="dica">Nenhuma gira cadastrada.</td></tr>`;

  $$(".btn-editar-gira").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const giraId = Number(btn.closest("tr").dataset.gira);
      try {
        await abrirModalGira(giraId);
      } catch (erro) { avisar(erro.message); }
    })
  );

  $$(".btn-remover-gira").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const giraId = Number(btn.closest("tr").dataset.gira);
      if (!confirm("Remover esta gira? A escala e as presenças também serão removidas.")) return;
      try {
        await api("DELETE", `/giras/${giraId}`);
        avisar("Gira removida.");
        await carregarVisaoGeral();
      } catch (erro) { avisar(erro.message); }
    })
  );
}

function renderizarIntegrantes() {
  $("#lista-integrantes").innerHTML = estado.pessoas.length
    ? estado.pessoas.map((p) => `
        <li data-id="${p.id}" class="${estado.integranteSelecionado === p.id ? "selecionado" : ""}">
          <span>${esc(p.nome)}</span><span class="etiqueta">${p.area} · ${p.cargo}${p.admin ? " · Administração" : ""}</span>
          ${p.notas ? `<small class="subtexto">${esc(p.notas)}</small>` : ""}
        </li>`).join("")
    : `<li class="dica">Nenhum integrante cadastrado.</li>`;

  $$("#lista-integrantes li[data-id]").forEach((li) =>
    li.addEventListener("click", () => {
      estado.integranteSelecionado = Number(li.dataset.id);
      renderizarIntegrantes();
    })
  );
}

// ---------------- CRUD de integrantes ----------------
function renderizarFuncoesAptas(aptas) {
  // Integrante novo entra apto a tudo; quem restringe é o usuário.
  const marcadas = new Set(aptas || FUNCOES_COM_APTIDAO);
  $("#integrante-funcoes").innerHTML = FUNCOES_COM_APTIDAO.map((funcao) => `
    <label class="funcao-apta">
      <input type="checkbox" class="check-funcao-apta" value="${esc(funcao)}"
        ${marcadas.has(funcao) ? "checked" : ""} />
      <span>${esc(ROTULO_APTIDAO[funcao] || funcao)}</span>
    </label>`).join("");
}

function abrirModalIntegrante(pessoa) {
  const form = $("#form-integrante");
  form.reset();
  $("#modal-integrante-titulo").textContent = pessoa ? "Editar integrante" : "Adicionar integrante";
  form.dataset.id = pessoa ? pessoa.id : "";
  if (pessoa) {
    form.nome.value = pessoa.nome || "";
    form.email.value = pessoa.email || "";
    form.telefone.value = pessoa.telefone || "";
    form.cargo.value = pessoa.cargo;
    form.area.value = pessoa.area;
    form.admin.checked = pessoa.admin ?? false;
    form.notas.value = pessoa.notas || "";
    form.mensalidade.value = pessoa.mensalidade ?? 0;
  }
  // Fora do `if`: no cadastro novo isto é que desenha as caixas, todas marcadas.
  renderizarFuncoesAptas(pessoa ? pessoa.funcoes_aptas : null);
  $("#modal-integrante").classList.add("aberto");
}

function pessoaSelecionada() {
  const pessoa = estado.pessoas.find((p) => p.id === estado.integranteSelecionado);
  if (!pessoa) avisar("Selecione um integrante na lista primeiro.");
  return pessoa;
}

$("#btn-adicionar").addEventListener("click", () => abrirModalIntegrante(null));
$("#btn-editar").addEventListener("click", () => {
  const pessoa = pessoaSelecionada();
  if (pessoa) abrirModalIntegrante(pessoa);
});
$("#btn-remover").addEventListener("click", async () => {
  const pessoa = pessoaSelecionada();
  if (!pessoa) return;
  if (!confirm(`Remover ${pessoa.nome}? Guias, escalas e pagamentos também serão removidos.`)) return;
  try {
    await api("DELETE", `/pessoas/${pessoa.id}`);
    estado.integranteSelecionado = null;
    avisar("Integrante removido.");
    await carregarVisaoGeral();
  } catch (erro) { avisar(erro.message); }
});

$("#form-integrante").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const form = evento.target;
  const corpo = {
    nome: form.nome.value.trim(),
    email: form.email.value.trim() || null,
    telefone: form.telefone.value.trim() || null,
    cargo: form.cargo.value,
    area: form.area.value,
    admin: form.admin.checked,
    notas: form.notas.value.trim() || null,
    mensalidade: Number(form.mensalidade.value || 0),
    ativo: 1,
    funcoes_aptas: $$("#integrante-funcoes .check-funcao-apta")
      .filter((check) => check.checked)
      .map((check) => check.value),
  };
  try {
    if (form.dataset.id) await api("PUT", `/pessoas/${form.dataset.id}`, corpo);
    else await api("POST", "/pessoas/", corpo);
    $("#modal-integrante").classList.remove("aberto");
    avisar("Integrante salvo.");
    await carregarVisaoGeral();
  } catch (erro) { avisar(erro.message); }
});

// ---------------- Cadastro de giras ----------------
function atualizarContagemGira() {
  const marcados = $$("#gira-trabalhadores .check-trabalhou").filter((c) => c.checked);
  const porCargo = new Map();
  marcados.forEach((check) => {
    const cargo = check.closest("[data-cargo]").dataset.cargo;
    porCargo.set(cargo, (porCargo.get(cargo) || 0) + 1);
  });
  const detalhe = CARGOS
    .filter((cargo) => porCargo.get(cargo))
    .map((cargo) => `${porCargo.get(cargo)} ${cargo}`)
    .join(" · ");
  $("#gira-contagem").textContent =
    `${marcados.length} trabalharam${detalhe ? ` (${detalhe})` : ""}`;
}

function renderizarTrabalhadores(escalasPorPessoa) {
  const guiasDe = (pessoaId) =>
    estado.entidades.filter((e) => e.medium_id === pessoaId);

  const grupos = CARGOS.map((cargo) => {
    const pessoas = estado.pessoas.filter((p) => p.cargo === cargo);
    if (!pessoas.length) return "";
    const linhas = pessoas.map((pessoa) => {
      const escala = escalasPorPessoa.get(pessoa.id);
      const guias = guiasDe(pessoa.id);
      const opcoes = [`<option value="">Sem incorporação</option>`]
        .concat(guias.map((g) =>
          `<option value="${g.id}" ${escala && escala.entidade_id === g.id ? "selected" : ""}>${esc(g.nome)} (${g.tipo})</option>`))
        .join("");
      return `
        <label class="trabalhador" data-pessoa="${pessoa.id}" data-cargo="${pessoa.cargo}">
          <input type="checkbox" class="check-trabalhou" ${escala ? "checked" : ""} />
          <span class="trabalhador-nome">${esc(pessoa.nome)}</span>
          <select class="select-entidade">${opcoes}</select>
        </label>`;
    }).join("");
    return `<fieldset class="grupo-cargo"><legend>${cargo}</legend>${linhas}</fieldset>`;
  }).join("");

  $("#gira-trabalhadores").innerHTML = grupos ||
    `<p class="dica">Cadastre integrantes antes de montar a escala.</p>`;

  $$("#gira-trabalhadores .check-trabalhou").forEach((check) =>
    check.addEventListener("change", atualizarContagemGira)
  );
  $$("#gira-trabalhadores .select-entidade").forEach((select) =>
    select.addEventListener("change", () => {
      if (select.value) {
        select.closest("label").querySelector(".check-trabalhou").checked = true;
        atualizarContagemGira();
      }
    })
  );
  atualizarContagemGira();
}

function renderizarFuncoes(sugestoes, existentes) {
  const elegiveis = estado.pessoas.filter((p) => CARGOS_FUNCAO.includes(p.cargo));
  if (!elegiveis.length) {
    $("#gira-funcoes").innerHTML =
      `<p class="dica">Nenhum médium de rodízio ou cambono ativo cadastrado.</p>`;
    return;
  }

  const jaSalvo = new Map(existentes.map((f) => [f.funcao, f.pessoa_id]));
  const sugeridoPor = new Map(sugestoes.map((s) => [s.funcao, s]));

  $("#gira-funcoes").innerHTML = FUNCOES.map((funcao) => {
    const sugestao = sugeridoPor.get(funcao);
    // Ao reeditar, o que já foi salvo manda; senão entra a sugestão do rodízio.
    const escolhido = jaSalvo.has(funcao)
      ? jaSalvo.get(funcao)
      : (sugestao ? sugestao.pessoa_id : null);
    // Só quem o cadastro marca como apto — o backend recusaria os demais.
    // Quem já está salvo continua listado mesmo se a aptidão mudou depois,
    // senão reabrir a gira apagaria silenciosamente o registro do que houve.
    const exigida = funcao === "Limpeza 2 - Pessoa 2" ? "Limpeza 2 - Pessoa 1" : funcao;
    const aptos = elegiveis.filter((p) =>
      (p.funcoes_aptas || []).includes(exigida) || p.id === escolhido);
    if (!aptos.length) {
      return `
        <label class="funcao" data-funcao="${esc(funcao)}">
          <span class="funcao-nome">${esc(funcao)}</span>
          <select class="select-funcao"><option value="">— ninguém apto —</option></select>
          <small class="subtexto">Nenhum elegível marcado como apto para esta função.</small>
        </label>`;
    }
    const opcoes = [`<option value="">— ninguém —</option>`].concat(
      aptos.map((p) =>
        `<option value="${p.id}" ${p.id === escolhido ? "selected" : ""}>${esc(p.nome)}</option>`)
    ).join("");
    const dica = sugestao && sugestao.nome
      ? `<small class="subtexto">Rodízio sugere: ${esc(sugestao.nome)}</small>`
      : "";
    return `
      <label class="funcao" data-funcao="${esc(funcao)}">
        <span class="funcao-nome">${esc(funcao)}</span>
        <select class="select-funcao">${opcoes}</select>
        ${dica}
      </label>`;
  }).join("");
}

async function abrirModalGira(giraId) {
  const form = $("#form-gira");
  form.reset();
  form.dataset.id = giraId || "";
  $("#modal-gira-titulo").textContent = giraId ? "Editar gira" : "Adicionar gira";

  const [pessoas, entidades] = await Promise.all([
    api("GET", "/pessoas/"),
    api("GET", "/entidades/"),
  ]);
  estado.pessoas = pessoas;
  estado.entidades = entidades;

  let escalasPorPessoa = new Map();
  let funcoesSalvas = [];
  if (giraId) {
    const [gira, escalas, funcoes] = await Promise.all([
      api("GET", `/giras/${giraId}`),
      api("GET", `/escalas/gira/${giraId}`),
      api("GET", `/giras/${giraId}/funcoes`),
    ]);
    form.data.value = gira.data.slice(0, 10);
    form.nome.value = gira.nome || "";
    form.tipo.value = gira.tipo;
    form.observacoes.value = gira.observacoes || "";
    escalasPorPessoa = new Map(escalas.map((e) => [e.pessoa_id, e]));
    funcoesSalvas = funcoes;
  } else {
    form.data.value = new Date().toISOString().slice(0, 10);
  }

  // Ao editar, a própria gira é excluída do histórico do rodízio.
  const sugestoes = await api(
    "GET",
    `/giras/funcoes/sugestoes${giraId ? `?gira_id=${giraId}` : ""}`
  );

  renderizarFuncoes(sugestoes, funcoesSalvas);
  renderizarTrabalhadores(escalasPorPessoa);
  $("#modal-gira").classList.add("aberto");
}

$("#btn-adicionar-gira").addEventListener("click", () =>
  abrirModalGira(null).catch((erro) => avisar(erro.message))
);

$("#form-gira").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const form = evento.target;
  const corpo = {
    nome: form.nome.value.trim() || null,
    tipo: form.tipo.value,
    data: `${form.data.value}T00:00:00`,
    observacoes: form.observacoes.value.trim() || null,
  };
  const trabalhadores = $$("#gira-trabalhadores .trabalhador")
    .filter((label) => label.querySelector(".check-trabalhou").checked)
    .map((label) => {
      const entidadeId = label.querySelector(".select-entidade").value;
      return {
        pessoa_id: Number(label.dataset.pessoa),
        entidade_id: entidadeId ? Number(entidadeId) : null,
        presente: true,
      };
    });

  const funcoes = $$("#gira-funcoes .funcao")
    .map((label) => ({
      funcao: label.dataset.funcao,
      pessoa_id: Number(label.querySelector(".select-funcao").value),
    }))
    .filter((f) => f.pessoa_id);

  try {
    const gira = form.dataset.id
      ? await api("PUT", `/giras/${form.dataset.id}`, corpo)
      : await api("POST", "/giras/", corpo);
    await api("PUT", `/giras/${gira.id}/escala`, { trabalhadores, funcoes });
    $("#modal-gira").classList.remove("aberto");
    avisar(`Gira salva com ${trabalhadores.length} trabalhador(es).`);
    await carregarVisaoGeral();
  } catch (erro) { avisar(erro.message); }
});

// ---------------- Planilha imprimível ----------------
$("#btn-planilha-gira").addEventListener("click", async () => {
  const form = $("#form-planilha");
  form.reset();
  form.data.value = new Date().toISOString().slice(0, 10);
  $("#planilha-previa").innerHTML = `<p class="dica">Carregando sugestões…</p>`;
  $("#modal-planilha").classList.add("aberto");

  try {
    const sugestoes = await api("GET", "/giras/funcoes/sugestoes");
    $("#planilha-previa").innerHTML =
      `<p class="dica">Funções que sairão preenchidas na planilha:</p><ul class="lista-simples">${
        sugestoes.map((s) =>
          `<li><strong>${esc(s.funcao)}</strong>: ${esc(s.nome) || "sem elegível disponível"}</li>`
        ).join("")
      }</ul>`;
  } catch (erro) {
    $("#planilha-previa").innerHTML = `<p class="dica">${esc(erro.message)}</p>`;
  }
});

$("#form-planilha").addEventListener("submit", (evento) => {
  evento.preventDefault();
  const form = evento.target;
  const url = `/planilhas/gira?tipo=${encodeURIComponent(form.tipo.value)}` +
    `&data=${encodeURIComponent(form.data.value)}`;
  // Âncora com download em vez de window.open: baixa sem abrir aba em branco.
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
  $("#modal-planilha").classList.remove("aberto");
  avisar("Planilha gerada.");
});

// ---------------- Financeiro / operacional ----------------
async function carregarFinanceiro() {
  const ano = Number($("#filtro-ano").value);
  const mes = Number($("#filtro-mes").value);

  const [resumo, pessoas, pagamentos, evolucao, giras] = await Promise.all([
    api("GET", `/pagamentos/resumo?ano=${ano}&mes=${mes}`),
    api("GET", "/pessoas/"),
    api("GET", `/pagamentos/?ano=${ano}&mes=${mes}`),
    api("GET", `/pagamentos/evolucao?ano=${ano}`),
    api("GET", "/giras/"),
  ]);
  estado.pessoas = pessoas;
  estado.pagamentos = pagamentos;

  $("#fin-previsto").textContent = moeda(resumo.total_previsto);
  $("#fin-recebido").textContent = moeda(resumo.total_recebido);
  $("#fin-pendente").textContent = moeda(resumo.total_pendente);
  $("#fin-inadimplentes").textContent = resumo.qtd_pendentes;

  renderizarGrafico(evolucao);
  renderizarPagamentos(ano, mes);
  renderizarSelecaoGiras(giras);
}

function renderizarGrafico(evolucao) {
  const maximo = Math.max(...evolucao.map((e) => e.total_recebido), 1);
  $("#grafico").innerHTML = evolucao.map((e) => `
    <div class="barra-wrap" title="${MESES[e.mes - 1]}: ${moeda(e.total_recebido)}">
      <span class="barra-valor">${e.total_recebido ? Math.round(e.total_recebido) : ""}</span>
      <div class="barra" style="height: ${(e.total_recebido / maximo) * 100}%"></div>
      <span class="barra-rotulo">${MESES[e.mes - 1].slice(0, 3)}</span>
    </div>`).join("");
}

function renderizarPagamentos(ano, mes) {
  const porPessoa = new Map(estado.pagamentos.map((p) => [p.pessoa_id, p]));

  $("#tabela-pagamentos").innerHTML = estado.pessoas.length
    ? estado.pessoas.map((pessoa) => {
        const pagamento = porPessoa.get(pessoa.id);
        const status = pagamento ? pagamento.status : "Pendente";
        // Sem lançamento ainda, o campo já vem com a mensalidade do cadastro: o
        // caso comum é pagar o valor cheio, e aí basta marcar Pago e salvar.
        // Havendo lançamento, mostra o que foi gravado — o que o usuário salvou
        // manda, inclusive quando pagou diferente da mensalidade.
        const valorPago = pagamento ? pagamento.valor : pessoa.mensalidade || 0;
        return `
          <tr data-pessoa="${pessoa.id}">
            <td><input type="checkbox" class="check-pessoa" ${status === "Pago" ? "" : "checked"} /></td>
            <td>${esc(pessoa.nome)}</td>
            <td>${esc(pessoa.telefone) || "—"}</td>
            <td>${moeda(pessoa.mensalidade)}</td>
            <td><input type="number" step="0.01" min="0" class="valor-pago"
                 value="${valorPago}" /></td>
            <td>
              <select class="status-pago">
                ${["Pago", "Pendente", "Isento"].map((s) =>
                  `<option value="${s}" ${s === status ? "selected" : ""}>${s}</option>`).join("")}
              </select>
            </td>
            <td><button class="btn btn-salvar-pagamento">Salvar</button></td>
          </tr>`;
      }).join("")
    : `<tr><td colspan="7" class="dica">Cadastre integrantes na Visão Geral.</td></tr>`;

  $$(".btn-salvar-pagamento").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const linha = btn.closest("tr");
      try {
        await api("POST", "/pagamentos/", {
          pessoa_id: Number(linha.dataset.pessoa),
          ano, mes,
          valor: Number(linha.querySelector(".valor-pago").value || 0),
          status: linha.querySelector(".status-pago").value,
        });
        avisar("Pagamento registrado.");
        await carregarFinanceiro();
      } catch (erro) { avisar(erro.message); }
    })
  );

  $("#check-todos").checked = false;
}

$("#check-todos").addEventListener("change", (evento) =>
  $$(".check-pessoa").forEach((c) => { c.checked = evento.target.checked; })
);

$("#btn-recarregar-fin").addEventListener("click", carregarFinanceiro);
$("#filtro-mes").addEventListener("change", carregarFinanceiro);

// ---------------- Presença nas giras ----------------
function renderizarSelecaoGiras(giras) {
  const select = $("#filtro-gira");
  if (!giras.length) {
    select.innerHTML = `<option value="">Nenhuma gira cadastrada</option>`;
    $("#tabela-presenca").innerHTML = `<tr><td colspan="4" class="dica">Cadastre uma gira para registrar presença.</td></tr>`;
    return;
  }
  const anterior = select.value;
  select.innerHTML = giras.map((g) =>
    `<option value="${g.id}">${dataCurta(g.data)} — ${esc(g.nome) || g.tipo}</option>`).join("");
  select.value = giras.some((g) => String(g.id) === anterior) ? anterior : String(giras[0].id);
  carregarPresenca();
}

$("#filtro-gira").addEventListener("change", carregarPresenca);

async function carregarPresenca() {
  const giraId = $("#filtro-gira").value;
  if (!giraId) return;
  const [escalas, entidades] = await Promise.all([
    api("GET", `/escalas/gira/${giraId}`),
    api("GET", "/entidades/"),
  ]);
  estado.entidades = entidades;
  const nomePessoa = (id) => (estado.pessoas.find((p) => p.id === id) || {}).nome || `#${id}`;
  const nomeEntidade = (id) =>
    id ? (entidades.find((e) => e.id === id) || {}).nome || "—" : "Sem incorporação";

  $("#tabela-presenca").innerHTML = escalas.length
    ? escalas.map((e) => `
        <tr data-escala="${e.id}">
          <td>${esc(nomePessoa(e.pessoa_id))}</td>
          <td>${esc(nomeEntidade(e.entidade_id))}</td>
          <td>${e.cargo}</td>
          <td><input type="checkbox" class="check-presenca" ${e.presente ? "checked" : ""} /></td>
        </tr>`).join("")
    : `<tr><td colspan="4" class="dica">Nenhum trabalhador nesta gira. Edite a gira na Visão Geral para montar a escala.</td></tr>`;

  $$(".check-presenca").forEach((check) =>
    check.addEventListener("change", async () => {
      const escalaId = check.closest("tr").dataset.escala;
      try {
        await api("PATCH", `/escalas/${escalaId}/presenca`, { presente: check.checked });
        avisar("Presença atualizada.");
      } catch (erro) {
        check.checked = !check.checked;
        avisar(erro.message);
      }
    })
  );
}

// ---------------- Módulo de mensagens ----------------
function abrirModalMensagem(destinatarios, textoPadrao) {
  if (!destinatarios.length) {
    avisar("Selecione ao menos um integrante.");
    return;
  }
  estado.destinatarios = destinatarios;
  $("#mensagem-destinatarios").textContent =
    destinatarios.map((d) => d.nome).join(", ");
  $("#mensagem-texto").value = textoPadrao || "";
  $("#mensagem-links").innerHTML = "";
  $("#modal-mensagem").classList.add("aberto");
}

$("#btn-mensagem-inadimplentes").addEventListener("click", () => {
  const selecionados = $$("#tabela-pagamentos tr")
    .filter((tr) => tr.querySelector(".check-pessoa")?.checked)
    .map((tr) => {
      const id = Number(tr.dataset.pessoa);
      return { id, nome: (estado.pessoas.find((p) => p.id === id) || {}).nome };
    });
  const mes = MESES[Number($("#filtro-mes").value) - 1];
  abrirModalMensagem(
    selecionados,
    `Axé, {primeiro_nome}! Passando para lembrar da contribuição de ${mes} no valor de R$ {valor}. Qualquer dúvida, fale com a gente. 🙏`
  );
});

$("#btn-gerar-mensagem").addEventListener("click", async () => {
  const mensagem = $("#mensagem-texto").value.trim();
  if (!mensagem) {
    avisar("Digite a mensagem.");
    return;
  }
  try {
    const resposta = await api("POST", "/mensagens/whatsapp", {
      pessoa_ids: estado.destinatarios.map((d) => d.id),
      mensagem,
    });
    $("#mensagem-links").innerHTML = resposta.destinatarios.map((d) =>
      d.whatsapp_url
        ? `<a href="${esc(d.whatsapp_url)}" target="_blank" rel="noopener">Enviar para ${esc(d.nome)} →</a>`
        : `<span class="erro">${esc(d.nome)}: ${esc(d.erro)}</span>`
    ).join("");
  } catch (erro) { avisar(erro.message); }
});

// ---------------- Visão espiritual ----------------
async function carregarEspiritual() {
  const integrantes = await api("GET", "/dashboard/espiritual");
  $("#lista-espiritual").innerHTML = integrantes.length
    ? integrantes.map((i) => `
        <li data-id="${i.pessoa.id}" class="${estado.espiritualSelecionado === i.pessoa.id ? "selecionado" : ""}">
          <span>${esc(i.pessoa.nome)}</span><span class="etiqueta">${i.entidades.length} guia(s)</span>
        </li>`).join("")
    : `<li class="dica">Nenhum integrante cadastrado.</li>`;

  $$("#lista-espiritual li[data-id]").forEach((li) =>
    li.addEventListener("click", () => {
      estado.espiritualSelecionado = Number(li.dataset.id);
      carregarEspiritual();
    })
  );

  const selecionado = integrantes.find((i) => i.pessoa.id === estado.espiritualSelecionado);
  $("#espiritual-titulo").textContent = selecionado
    ? `Guias de ${selecionado.pessoa.nome}`
    : "Guias e entidades";
  $("#tabela-entidades").innerHTML = selecionado
    ? (selecionado.entidades.length
        ? selecionado.entidades.map((e) => `<tr><td>${esc(e.nome)}</td><td>${e.tipo}</td></tr>`).join("")
        : `<tr><td colspan="2" class="dica">Nenhum guia cadastrado.</td></tr>`)
    : `<tr><td colspan="2" class="dica">Selecione um integrante.</td></tr>`;
}

$("#form-entidade").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (!estado.espiritualSelecionado) {
    avisar("Selecione um integrante primeiro.");
    return;
  }
  const form = evento.target;
  try {
    await api("POST", "/entidades/", {
      nome: form.nome.value.trim(),
      tipo: form.tipo.value,
      medium_id: estado.espiritualSelecionado,
    });
    form.reset();
    avisar("Guia adicionado.");
    await carregarEspiritual();
  } catch (erro) { avisar(erro.message); }
});

// ---------------- Sessão ----------------
async function carregarUsuario() {
  try {
    const { auth_habilitada, usuario } = await api("GET", "/auth/eu");
    $("#usuario").innerHTML = auth_habilitada && usuario
      ? `<span class="etiqueta">${esc(usuario.email)}</span> <a class="btn" href="/logout">Sair</a>`
      : "";
  } catch (erro) { /* login desabilitado */ }
}

// ---------------- Estoque ----------------
async function carregarEstoque() {
  const [itens, resumo] = await Promise.all([
    api("GET", "/estoque/itens"),
    api("GET", "/estoque/resumo"),
  ]);
  estado.itensEstoque = itens;
  renderizarAlertaEstoque(resumo);
  renderizarEstoque();
}

// Só o número, para a Visão Geral não pagar a lista inteira.
async function atualizarCardEstoque() {
  try {
    const resumo = await api("GET", "/estoque/resumo");
    $("#kpi-estoque-alerta").textContent = resumo.qtd_em_alerta;
  } catch (erro) { /* estoque ainda vazio não é problema na visão geral */ }
}

function renderizarAlertaEstoque(resumo) {
  const painel = $("#painel-alerta-estoque");
  painel.hidden = !resumo.qtd_em_alerta;
  $("#lista-alerta-estoque").innerHTML = resumo.itens_em_alerta
    .map((i) => `<li><strong>${esc(i.nome)}</strong> — ${i.quantidade} ${esc(i.unidade)}
      (mínimo ${i.minimo_alerta})</li>`).join("");
  $("#kpi-estoque-alerta").textContent = resumo.qtd_em_alerta;
}

function renderizarEstoque() {
  const filtro = $("#filtro-estoque").value.trim().toLowerCase();
  const itens = estado.itensEstoque.filter((i) =>
    !filtro || i.nome.toLowerCase().includes(filtro));

  $("#tabela-estoque").innerHTML = itens.length
    ? itens.map((item) => `
        <tr data-item="${item.id}" class="${item.em_alerta ? "linha-alerta" : ""}">
          <td>${esc(item.nome)}${item.em_alerta ? ' <span class="etiqueta-alerta">repor</span>' : ""}</td>
          <td>${esc(item.categoria) || "—"}</td>
          <td><input type="number" step="1" min="0" class="qtd-item" value="${item.quantidade}" />
              <span class="etiqueta">${esc(item.unidade)}</span></td>
          <td>${item.minimo_alerta === null ? "—" : item.minimo_alerta}</td>
          <td>${item.contar_por_foto ? "Sim" : "Só na mão"}</td>
          <td class="acoes">
            <button class="btn btn-salvar-item">Salvar</button>
            <button class="btn btn-editar-item">Editar</button>
            <button class="btn btn-perigo btn-remover-item">Remover</button>
          </td>
        </tr>`).join("")
    : `<tr><td colspan="6" class="dica">${estado.itensEstoque.length
        ? "Nenhum item com esse nome."
        : "Nenhum item cadastrado. Use Adicionar item para começar."}</td></tr>`;

  $$("#tabela-estoque .btn-salvar-item").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const linha = btn.closest("tr");
      try {
        await api("POST", `/estoque/itens/${linha.dataset.item}/movimentos`, {
          quantidade: Number(linha.querySelector(".qtd-item").value || 0),
          motivo: "Conferência manual",
        });
        avisar("Quantidade atualizada.");
        await carregarEstoque();
      } catch (erro) { avisar(erro.message); }
    })
  );

  $$("#tabela-estoque .btn-editar-item").forEach((btn) =>
    btn.addEventListener("click", () => {
      const id = Number(btn.closest("tr").dataset.item);
      abrirModalItem(estado.itensEstoque.find((i) => i.id === id));
    })
  );

  $$("#tabela-estoque .btn-remover-item").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = Number(btn.closest("tr").dataset.item);
      const item = estado.itensEstoque.find((i) => i.id === id);
      if (!confirm(`Remover ${item.nome}? O histórico de movimentos vai junto.`)) return;
      try {
        await api("DELETE", `/estoque/itens/${id}`);
        avisar("Item removido.");
        await carregarEstoque();
      } catch (erro) { avisar(erro.message); }
    })
  );
}

function abrirModalItem(item) {
  const form = $("#form-item");
  form.reset();
  form.dataset.id = item ? item.id : "";
  $("#modal-item-titulo").textContent = item ? "Editar item" : "Adicionar item";
  // A quantidade só entra no cadastro do item novo; depois disso ela muda por
  // conferência na tabela, para o histórico não perder o que aconteceu.
  $("#campo-quantidade-inicial").hidden = Boolean(item);
  if (item) {
    form.nome.value = item.nome;
    form.categoria.value = item.categoria || "";
    form.unidade.value = item.unidade;
    form.minimo_alerta.value = item.minimo_alerta === null ? "" : item.minimo_alerta;
    form.contar_por_foto.checked = item.contar_por_foto;
    form.notas.value = item.notas || "";
  } else {
    form.unidade.value = "unidade";
    form.contar_por_foto.checked = true;
  }
  $("#modal-item").classList.add("aberto");
}

$("#btn-adicionar-item").addEventListener("click", () => abrirModalItem(null));
$("#filtro-estoque").addEventListener("input", renderizarEstoque);
$("#card-estoque").addEventListener("click", () => irParaAba("estoque"));

$("#form-item").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const form = evento.target;
  const minimo = form.minimo_alerta.value.trim();
  const corpo = {
    nome: form.nome.value.trim(),
    categoria: form.categoria.value.trim() || null,
    unidade: form.unidade.value.trim() || "unidade",
    minimo_alerta: minimo === "" ? null : Number(minimo),
    contar_por_foto: form.contar_por_foto.checked,
    notas: form.notas.value.trim() || null,
  };
  try {
    if (form.dataset.id) {
      await api("PUT", `/estoque/itens/${form.dataset.id}`, corpo);
    } else {
      await api("POST", "/estoque/itens",
        { ...corpo, quantidade: Number(form.quantidade.value || 0) });
    }
    $("#modal-item").classList.remove("aberto");
    avisar("Item salvo.");
    await carregarEstoque();
  } catch (erro) { avisar(erro.message); }
});

// ---------------- Inicialização ----------------
function inicializar() {
  const hoje = new Date();
  preencherSelect($("#integrante-cargo"), CARGOS);
  preencherSelect($("#integrante-area"), AREAS);
  preencherSelect($("#entidade-tipo"), LINHAS);
  preencherSelect($("#gira-tipo"), LINHAS);
  preencherSelect($("#planilha-tipo"), LINHAS);
  preencherSelect($("#filtro-mes"), MESES.map((m, i) => ({ valor: i + 1, rotulo: m })));
  $("#filtro-mes").value = String(hoje.getMonth() + 1);
  $("#filtro-ano").value = String(hoje.getFullYear());
  carregarUsuario();
  carregarVisaoGeral().catch((erro) => avisar(erro.message));
  atualizarCardEstoque();
}

inicializar();
