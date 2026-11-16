// Motor da conferência no navegador: tradução de conferencia/leitura.py, cruzamento.py,
// explicacao.py (modo regras) e avaliar.py. tests/test_painel.py roda este motor num navegador
// e compara o resultado, divergência por divergência, com o do Python nos mesmos dados.
// Valores em dinheiro são inteiros em centavos, para não ter erro de arredondamento.
(function (global) {
  "use strict";

  const TIPOS = {
    PEDIDO_SEM_NOTA: "Pedido concluído sem nota autorizada",
    NOTA_CANCELADA: "Pedido concluído, mas a única nota está cancelada",
    VALOR_DIVERGENTE: "Valor da nota diferente do valor do pedido",
    NOTA_DUPLICADA: "Mais de uma nota autorizada para o mesmo pedido",
    NOTA_SEM_PEDIDO: "Nota que não corresponde a nenhum pedido",
    NOTA_PEDIDO_CANCELADO: "Nota autorizada para um pedido cancelado",
    CHAVE_INVALIDA: "Chave de acesso com dígito verificador errado",
  };

  const PADRAO_PEDIDO = /(?:\bped(?:ido)?\b\.?|#)[^\d\n|]{0,15}?(\d{4,})/i;
  const CANCELAMENTO = "110111";
  const EVENTO_ACEITO = new Set(["135", "155"]);
  const POR_CHAVE = new Set(["CHAVE_INVALIDA", "NOTA_SEM_PEDIDO"]);

  // ---------- dinheiro ----------
  // Aceita "1234.56", "1234,56" e "1.234,56" (CSV salvo pelo Excel em português).
  function centavos(texto) {
    let t = String(texto ?? "").trim().replace(/^R\$\s*/, "");
    if (!t) return 0;
    if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
    const n = Number(t);
    if (!Number.isFinite(n)) throw new Error(`valor inválido: "${texto}"`);
    return Math.round(n * 100);
  }

  function brl(c) {
    const neg = c < 0;
    const abs = Math.abs(c);
    const inteiro = Math.floor(abs / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return `R$ ${neg ? "-" : ""}${inteiro},${String(abs % 100).padStart(2, "0")}`;
  }

  // ---------- CSV ----------
  function lerCsv(texto) {
    texto = texto.replace(/^﻿/, "");
    const primeira = texto.split(/\r?\n/, 1)[0];
    const sep = (primeira.match(/;/g) || []).length > (primeira.match(/,/g) || []).length ? ";" : ",";
    const linhas = [];
    let campo = "", linha = [], aspas = false;
    for (let i = 0; i < texto.length; i++) {
      const ch = texto[i];
      if (aspas) {
        if (ch === '"' && texto[i + 1] === '"') { campo += '"'; i++; }
        else if (ch === '"') aspas = false;
        else campo += ch;
      } else if (ch === '"') aspas = true;
      else if (ch === sep) { linha.push(campo); campo = ""; }
      else if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && texto[i + 1] === "\n") i++;
        linha.push(campo); campo = "";
        if (linha.some((c) => c !== "")) linhas.push(linha);
        linha = [];
      } else campo += ch;
    }
    linha.push(campo);
    if (linha.some((c) => c !== "")) linhas.push(linha);
    const cab = (linhas.shift() || []).map((c) => c.trim().toLowerCase());
    return linhas.map((l) => Object.fromEntries(cab.map((c, i) => [c, (l[i] ?? "").trim()])));
  }

  function tipoCsv(texto) {
    const cab = texto.replace(/^﻿/, "").split(/\r?\n/, 1)[0].toLowerCase();
    if (cab.includes("causa")) return "gabarito";
    if (cab.includes("item") && cab.includes("quantidade")) return "itens";
    if (cab.includes("pedido_id") && cab.includes("valor_total")) return "pedidos";
    return null;
  }

  // ---------- XML ----------
  // Procura por nome local, com ou sem o namespace da NF-e.
  function filho(el, nome) {
    if (!el) return null;
    for (const c of el.children) if (c.localName === nome) return c;
    return null;
  }
  function caminho(el, path) {
    for (const parte of path.split("/")) el = filho(el, parte);
    return el;
  }
  function txt(el, path, padrao = "") {
    const e = path ? caminho(el, path) : el;
    return e && e.textContent ? e.textContent.trim() : padrao;
  }
  function primeiro(doc, nome) {
    return doc.getElementsByTagNameNS("*", nome)[0] || null;
  }

  function extrairPedido(texto) {
    const m = PADRAO_PEDIDO.exec(texto || "");
    return m ? m[1] : null;
  }

  function lerXml(nome, conteudo) {
    const doc = new DOMParser().parseFromString(conteudo, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error("XML mal formado");
    const raiz = doc.documentElement.localName;
    if (raiz === "procEventoNFe") {
      const inf = caminho(primeiro(doc, "evento"), "infEvento");
      const ret = caminho(primeiro(doc, "retEvento"), "infEvento");
      return {
        tipo: "evento",
        evento: {
          chave: txt(inf, "chNFe"), tipo: txt(inf, "tpEvento"), descricao: txt(inf, "detEvento/descEvento"),
          data: txt(inf, "dhEvento"), cstat: ret ? txt(ret, "cStat") : "", motivo: ret ? txt(ret, "xMotivo") : "",
          arquivo: nome,
        },
      };
    }
    if (raiz !== "nfeProc" && raiz !== "NFe") throw new Error(`não é NF-e nem evento (<${raiz}>)`);
    const inf = primeiro(doc, "infNFe");
    if (!inf) throw new Error("sem <infNFe>");
    const complemento = txt(inf, "infAdic/infCpl");
    const prot = primeiro(doc, "protNFe");
    const status = prot ? txt(prot, "infProt/cStat") : "";
    const itens = [];
    for (const det of inf.children) {
      if (det.localName !== "det") continue;
      const prod = filho(det, "prod");
      itens.push({
        codigo: txt(prod, "cProd"), descricao: txt(prod, "xProd"),
        quantidade: Number(txt(prod, "qCom", "0")), valorUnitario: centavos(txt(prod, "vUnCom", "0")),
        valorTotal: centavos(txt(prod, "vProd", "0")),
      });
    }
    return {
      tipo: "nota",
      nota: {
        chave: (inf.getAttribute("Id") || "").replace(/^NFe/, ""),
        numero: parseInt(txt(inf, "ide/nNF", "0"), 10),
        emissao: txt(inf, "ide/dhEmi"),
        valor: centavos(txt(inf, "total/ICMSTot/vNF", "0")),
        desconto: centavos(txt(inf, "total/ICMSTot/vDesc", "0")),
        frete: centavos(txt(inf, "total/ICMSTot/vFrete", "0")),
        pedidoId: extrairPedido(complemento),
        situacao: status === "100" ? "AUTORIZADA" : status === "101" ? "CANCELADA" : `OUTRA(${status})`,
        cstat: status,
        arquivo: nome, itens, textoComplementar: complemento, eventos: [], arquivosRepetidos: [],
      },
    };
  }

  // Recebe [{nome, conteudo}] e separa pedidos, itens, gabarito, notas e eventos.
  function lerArquivos(arquivos) {
    const avisos = [];
    let pedidosCsv = null, itensCsv = null, gabaritoCsv = null;
    const xmls = [];
    for (const a of arquivos) {
      const nome = a.nome.split("/").pop();
      if (/\.xml$/i.test(nome)) xmls.push({ nome, conteudo: a.conteudo });
      else if (/\.csv$/i.test(nome)) {
        const t = tipoCsv(a.conteudo);
        if (t === "pedidos") pedidosCsv = a.conteudo;
        else if (t === "itens") itensCsv = a.conteudo;
        else if (t === "gabarito") gabaritoCsv = a.conteudo;
        else avisos.push(`${nome}: CSV com colunas desconhecidas, ignorado`);
      } else avisos.push(`${nome}: formato não reconhecido, ignorado`);
    }

    const itensPorPedido = {};
    if (itensCsv) for (const l of lerCsv(itensCsv)) {
      const qtd = Number(String(l.quantidade).replace(",", "."));
      const unit = centavos(l.valor_unitario);
      (itensPorPedido[l.pedido_id] ||= []).push({
        descricao: l.item, quantidade: qtd, valorUnitario: unit, valorTotal: Math.round(qtd * unit),
      });
    }
    const pedidos = pedidosCsv ? lerCsv(pedidosCsv).map((l) => ({
      pedidoId: l.pedido_id, dataHora: l.data_hora, subtotal: centavos(l.subtotal),
      descontoLoja: centavos(l.desconto_loja), taxaEntrega: centavos(l.taxa_entrega),
      valorTotal: centavos(l.valor_total), status: (l.status || "").toUpperCase(),
      itens: itensPorPedido[l.pedido_id] || [],
    })) : [];

    // Mesma ordem do Python: arquivos em ordem alfabética; o mesmo XML duas vezes é uma nota só.
    xmls.sort((a, b) => (a.nome < b.nome ? -1 : a.nome > b.nome ? 1 : 0));
    const notas = new Map();
    const eventos = [];
    for (const x of xmls) {
      try {
        const r = lerXml(x.nome, x.conteudo);
        if (r.tipo === "evento") eventos.push(r.evento);
        else if (notas.has(r.nota.chave)) notas.get(r.nota.chave).arquivosRepetidos.push(x.nome);
        else notas.set(r.nota.chave, r.nota);
      } catch (e) {
        avisos.push(`${x.nome}: ${e.message}, ignorado`);
      }
    }
    let eventosSemNota = 0;
    for (const ev of eventos) {
      const nota = notas.get(ev.chave);
      if (!nota) { eventosSemNota++; continue; }
      nota.eventos.push(ev);
      if (ev.tipo === CANCELAMENTO && EVENTO_ACEITO.has(ev.cstat)) nota.situacao = "CANCELADA";
    }
    if (eventosSemNota) avisos.push(`${eventosSemNota} evento(s) de nota que não está entre os arquivos`);
    const repetidos = [...notas.values()].reduce((s, n) => s + n.arquivosRepetidos.length, 0);

    return {
      pedidos, notas: [...notas.values()], eventos, avisos, repetidos,
      temItens: !!itensCsv,
      gabarito: gabaritoCsv ? lerCsv(gabaritoCsv) : null,
    };
  }

  // ---------- regras (cruzamento.py) ----------
  function digitoVerificador(chave43) {
    let soma = 0, peso = 2;
    for (let i = chave43.length - 1; i >= 0; i--) {
      soma += Number(chave43[i]) * peso;
      peso = peso === 9 ? 2 : peso + 1;
    }
    const resto = soma % 11;
    return resto < 2 ? 0 : 11 - resto;
  }
  function chaveValida(c) {
    return c.length === 44 && /^\d+$/.test(c) && digitoVerificador(c.slice(0, 43)) === Number(c[43]);
  }

  function conferir(pedidos, notas) {
    const achados = [];
    const porPedido = new Map();
    const ids = new Set(pedidos.map((p) => p.pedidoId));

    for (const nota of notas) {
      if (!chaveValida(nota.chave)) achados.push(["CHAVE_INVALIDA", nota.pedidoId, [nota.chave], { arquivo: nota.arquivo }]);
      if (ids.has(nota.pedidoId)) {
        if (!porPedido.has(nota.pedidoId)) porPedido.set(nota.pedidoId, []);
        porPedido.get(nota.pedidoId).push(nota);
      } else if (nota.situacao === "AUTORIZADA") {
        achados.push(["NOTA_SEM_PEDIDO", nota.pedidoId, [nota.chave], {
          valor_nota: nota.valor, emissao: nota.emissao, texto_pedido_na_nota: nota.pedidoId,
          texto_complementar: nota.textoComplementar,
        }]);
      }
    }

    for (const p of pedidos) {
      const doPedido = porPedido.get(p.pedidoId) || [];
      const autorizadas = doPedido.filter((n) => n.situacao === "AUTORIZADA");
      const canceladas = doPedido.filter((n) => n.situacao === "CANCELADA");

      if (p.status === "CANCELADO") {
        if (autorizadas.length) {
          const rejeitados = autorizadas.flatMap((n) => n.eventos.filter((e) => !EVENTO_ACEITO.has(e.cstat))
            .map((e) => `${e.descricao || e.tipo}: ${e.cstat} ${e.motivo}`));
          achados.push(["NOTA_PEDIDO_CANCELADO", p.pedidoId, autorizadas.map((n) => n.chave),
            { valor_nota: autorizadas[0].valor, eventos_rejeitados: rejeitados }]);
        }
        continue;
      }
      if (!autorizadas.length) {
        achados.push([canceladas.length ? "NOTA_CANCELADA" : "PEDIDO_SEM_NOTA", p.pedidoId,
          canceladas.map((n) => n.chave), { valor_pedido: p.valorTotal, data_hora_pedido: p.dataHora }]);
        continue;
      }
      if (autorizadas.length > 1) {
        achados.push(["NOTA_DUPLICADA", p.pedidoId, autorizadas.map((n) => n.chave),
          { valor_pedido: p.valorTotal, qtd_notas: autorizadas.length }]);
      }
      const nota = autorizadas[0];
      const diferenca = nota.valor - p.valorTotal;
      if (diferenca !== 0) {
        achados.push(["VALOR_DIVERGENTE", p.pedidoId, [nota.chave], {
          valor_pedido: p.valorTotal, valor_nota: nota.valor, diferenca,
          desconto_pedido: p.descontoLoja, desconto_nota: nota.desconto,
          taxa_entrega_pedido: p.taxaEntrega, frete_nota: nota.frete,
        }]);
      }
    }
    return achados.map(([tipo, pedidoId, chaves, fatos], i) => ({
      id: `D${String(i + 1).padStart(2, "0")}`, tipo, pedidoId, chaves, fatos,
    }));
  }

  // ---------- explicação por regras (explicacao.py) ----------
  function explicarPorRegras(d) {
    const f = d.fatos;
    const pid = d.pedidoId || "sem número";
    if (d.tipo === "VALOR_DIVERGENTE") {
      const dif = f.diferenca;
      let causa, explicacao, acao;
      if (dif === f.desconto_pedido && dif > 0) {
        causa = "desconto_fora_da_nota";
        explicacao = `A nota do pedido ${pid} saiu ${brl(dif)} acima do valor pago, exatamente o desconto dado ao cliente.`;
        acao = "Conferir com o contador como corrigir; o imposto foi calculado sobre um valor maior.";
      } else if (-dif === f.taxa_entrega_pedido && dif < 0) {
        causa = "taxa_entrega_fora_da_nota";
        explicacao = `A nota do pedido ${pid} ficou ${brl(-dif)} abaixo do pago, o valor da taxa de entrega.`;
        acao = "Emitir nota complementar ou ajustar o emissor para incluir a taxa de entrega.";
      } else {
        causa = "outra";
        explicacao = `A nota do pedido ${pid} tem diferença de ${brl(dif)} que não bate com desconto nem taxa.`;
        acao = "Abrir o pedido e a nota lado a lado e conferir os itens.";
      }
      return { divergencia_id: d.id, prioridade: "alta", causa_provavel: causa, explicacao, acao };
    }
    const tabela = {
      PEDIDO_SEM_NOTA: ["alta", "nota_nao_emitida", `O pedido ${pid} foi entregue e não tem nota.`, "Emitir a nota da venda."],
      NOTA_CANCELADA: ["alta", "nota_cancelada_sem_substituta", `A nota do pedido ${pid} foi cancelada e nenhuma outra foi emitida.`, "Emitir uma nova nota para o pedido."],
      NOTA_DUPLICADA: ["alta", "emissao_em_duplicidade", `O pedido ${pid} tem ${f.qtd_notas ?? 2} notas autorizadas.`, "Cancelar a nota em duplicidade dentro do prazo."],
      NOTA_SEM_PEDIDO: ["media", "nota_sem_vinculo_com_pedido", "Existe uma nota autorizada que não aponta para nenhum pedido.", "Descobrir a que venda a nota se refere."],
      NOTA_PEDIDO_CANCELADO: ["alta", "pedido_cancelado_apos_emissao", `O pedido ${pid} foi cancelado, mas a nota continua autorizada.`, "Cancelar a nota."],
      CHAVE_INVALIDA: ["media", "chave_digitada_ou_gerada_errada", "A chave de acesso desta nota tem o dígito verificador errado.", "Conferir o XML original no portal da SEFAZ."],
    };
    const [prioridade, causa_provavel, explicacao, acao] = tabela[d.tipo];
    return { divergencia_id: d.id, prioridade, causa_provavel, explicacao, acao };
  }

  // ---------- avaliação contra o gabarito (avaliar.py) ----------
  function identificador(tipo, pedidoId, chave) {
    return POR_CHAVE.has(tipo) ? `${tipo}|${chave || ""}` : `${tipo}|${pedidoId || ""}`;
  }

  function avaliar(gabaritoLinhas, divergencias, explicacoes) {
    const gabarito = new Map(gabaritoLinhas.map((l) => [identificador(l.tipo, l.pedido_id, l.chave), l.causa]));
    const causas = new Map(explicacoes.map((e) => [e.divergencia_id, e.causa_provavel]));
    const encontrados = new Map(divergencias.map((d) => [identificador(d.tipo, d.pedidoId, d.chaves[0]), causas.get(d.id)]));
    const porDivergencia = {};
    for (const d of divergencias) {
      const id = identificador(d.tipo, d.pedidoId, d.chaves[0]);
      porDivergencia[d.id] = gabarito.has(id) ? { esperado: gabarito.get(id) } : { falsoPositivo: true };
    }
    const porCausa = {};
    let vp = 0, certas = 0;
    for (const [id, causa] of gabarito) {
      if (!encontrados.has(id)) continue;
      vp++;
      const ok = encontrados.get(id) === causa;
      certas += ok;
      (porCausa[causa] ||= { total: 0, acertos: 0 }).total++;
      porCausa[causa].acertos += ok;
    }
    const fp = [...encontrados.keys()].filter((id) => !gabarito.has(id)).length;
    return {
      plantadas: gabarito.size, verdadeiros: vp, falsosPositivos: fp, causaCerta: certas,
      recall: gabarito.size ? vp / gabarito.size : 1, precisao: vp + fp ? vp / (vp + fp) : 1,
      porCausa, porDivergencia,
      naoEncontradas: [...gabarito.keys()].filter((id) => !encontrados.has(id)),
    };
  }

  // ---------- tudo junto ----------
  function rodar(arquivos) {
    const dados = lerArquivos(arquivos);
    const divergencias = conferir(dados.pedidos, dados.notas);
    const explicacoes = divergencias.map(explicarPorRegras);
    const avaliacao = dados.gabarito ? avaliar(dados.gabarito, divergencias, explicacoes) : null;
    return { ...dados, divergencias, explicacoes, avaliacao };
  }

  global.Conferencia = { rodar, lerArquivos, conferir, explicarPorRegras, avaliar, chaveValida, extrairPedido, centavos, brl, TIPOS };
})(window);
