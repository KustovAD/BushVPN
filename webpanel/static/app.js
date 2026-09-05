const app = document.getElementById("app");
const state = {
  user: null,
  meta: null,
  view: "home",
  authTab: "login",
  servers: [],
  legal: null,
  invoice: null,
  link: null,
  toastTimer: null,
};

const NAV = [
  ["home", "Главная", "🌿"],
  ["key", "Ключ", "🔑"],
  ["how", "Подключение", "📘"],
  ["servers", "Серверы", "🌍"],
  ["pay", "Пополнить", "💳"],
  ["bonus", "Бонус", "🎁"],
  ["ref", "Друзья", "🔗"],
  ["account", "Аккаунт", "👤"],
  ["faq", "Вопросы", "❓"],
];

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function toast(text) {
  document.querySelector(".toast")?.remove();
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.appendChild(el);
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.remove(), 2600);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  let data = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) {
    throw new Error(data.detail || "Ошибка запроса");
  }
  return data;
}

function refFromUrl() {
  const n = Number(new URLSearchParams(location.search).get("ref") || "");
  return Number.isFinite(n) && n !== 0 ? n : null;
}

function render() {
  if (!state.user) renderAuth();
  else renderApp();
}

function renderAuth() {
  const tab = state.authTab;
  app.innerHTML = `
    <div class="auth-wrap">
      <div class="card auth-card">
        <div class="brand" style="padding:0 0 12px">
          <div class="logo">🌿</div>
          <div>
            <h1>BushVPN</h1>
            <small>Запасной вход, если Telegram недоступен</small>
          </div>
        </div>
        <div class="tabs">
          <button class="${tab === "login" ? "active" : ""}" data-tab="login">Вход</button>
          <button class="${tab === "register" ? "active" : ""}" data-tab="register">Регистрация</button>
          <button class="${tab === "claim" ? "active" : ""}" data-tab="claim">Есть ключ</button>
        </div>
        <p class="msg" id="auth-msg"></p>
        <form id="auth-form">
          <div class="field">
            <label>Логин</label>
            <input name="username" autocomplete="username" required placeholder="bush_user">
          </div>
          <div class="field">
            <label>Пароль</label>
            <input name="password" type="password" autocomplete="${tab === "login" ? "current-password" : "new-password"}" required placeholder="минимум 6 символов">
          </div>
          ${
            tab === "claim"
              ? `<div class="field"><label>UUID из ключа или Happ</label><input name="uuid" required placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"></div>`
              : ""
          }
          ${
            tab !== "login"
              ? `<label class="check"><input type="checkbox" name="accept" required> Принимаю <a href="#" data-view="terms">соглашение</a> и <a href="#" data-view="privacy">политику</a></label>`
              : ""
          }
          <button class="btn wide" type="submit">${
            tab === "login" ? "Войти" : tab === "claim" ? "Привязать и войти" : "Создать аккаунт"
          }</button>
        </form>
        <p class="lead" style="margin:16px 0 0;font-size:13px">
          Новый аккаунт получает 7 дней бесплатно. Уже есть бот — вкладка «Есть ключ».
          Привязка Telegram: после входа откройте «Аккаунт».
        </p>
      </div>
    </div>`;

  app.querySelectorAll("[data-tab]").forEach((btn) => {
    btn.onclick = () => {
      state.authTab = btn.dataset.tab;
      render();
    };
  });
  app.querySelectorAll("[data-view]").forEach((a) => {
    a.onclick = async (e) => {
      e.preventDefault();
      await openLegal(a.dataset.view);
    };
  });
  app.querySelector("#auth-form").onsubmit = onAuth;
}

async function onAuth(e) {
  e.preventDefault();
  const form = e.target;
  const msg = document.getElementById("auth-msg");
  msg.textContent = "";
  const body = {
    username: form.username.value.trim(),
    password: form.password.value,
    accept: !!form.accept?.checked,
    uuid: form.uuid?.value.trim() || null,
    ref: refFromUrl(),
  };
  try {
    const path =
      state.authTab === "login" ? "/api/auth/login" : "/api/auth/register";
    state.user = await api(path, { method: "POST", body: JSON.stringify(body) });
    if (state.user.trial) toast("Вам начислено 7 дней бесплатно");
    state.view = "home";
    render();
  } catch (err) {
    msg.textContent = err.message;
  }
}

function renderApp() {
  const u = state.user;
  const nav = NAV.map(
    ([id, label, icon]) =>
      `<button class="nav-btn ${state.view === id ? "active" : ""}" data-nav="${id}">${icon}<span>${label}</span></button>`
  ).join("");
  const admin = u.is_admin
    ? `<button class="nav-btn ${state.view === "admin" ? "active" : ""}" data-nav="admin">🛠<span>Админ</span></button>`
    : "";

  app.innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="logo">🌿</div>
          <div><h1>BushVPN</h1><small>${esc(u.web_username || "аккаунт")}</small></div>
        </div>
        ${nav}
        ${admin}
        <div class="spacer"></div>
        <button class="nav-btn logout-btn" id="logout">⎋<span>Выйти</span></button>
      </aside>
      <main class="main" id="page"></main>
    </div>`;

  app.querySelectorAll("[data-nav]").forEach((btn) => {
    btn.onclick = () => {
      state.view = btn.dataset.nav;
      render();
    };
  });
  document.getElementById("logout").onclick = async () => {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
    state.user = null;
    render();
  };
  renderPage();
}

function statusBadge(u) {
  if (u.active) return `<span class="badge">активна · ${u.days_left} дн.</span>`;
  return `<span class="badge danger">подписка истекла</span>`;
}

function renderPage() {
  const page = document.getElementById("page");
  const views = {
    home: viewHome,
    key: viewKey,
    how: viewHow,
    servers: viewServers,
    pay: viewPay,
    bonus: viewBonus,
    ref: viewRef,
    account: viewAccount,
    faq: viewFaq,
    terms: () => viewLegal("terms"),
    privacy: () => viewLegal("privacy"),
    admin: viewAdmin,
  };
  const fn = views[state.view] || viewHome;
  const result = fn();
  if (result instanceof Promise) {
    page.innerHTML = `<p class="lead">Загрузка…</p>`;
    result.then((html) => {
      page.innerHTML = html;
      bindPage();
    });
  } else {
    page.innerHTML = result;
    bindPage();
  }
}

function viewHome() {
  const u = state.user;
  return `
    <p class="badge">${esc(u.server_label || "сервер не выбран")}</p>
    <h2 class="page-title">С возвращением</h2>
    <p class="lead">Все функции Telegram-бота доступны здесь. Если мессенджер снова заработает — аккаунты останутся связанными.</p>
    <div class="grid cols-2">
      <div class="card">
        ${statusBadge(u)}
        <div class="stat" style="margin-top:16px">${u.days_left}</div>
        <div class="stat-label">дней подписки</div>
        <div class="row" style="margin-top:18px">
          <button class="btn" data-nav="pay">Пополнить</button>
          <button class="btn ghost" data-nav="key">Получить ключ</button>
        </div>
      </div>
      <div class="card">
        <h3>Быстрые действия</h3>
        <div class="row">
          <button class="btn ghost" data-nav="servers">Сменить сервер</button>
          <button class="btn ghost" data-nav="how">Как подключиться</button>
          <button class="btn ghost" data-nav="bonus">Бонус +7 дней</button>
          <button class="btn ghost" data-nav="account">Привязать Telegram</button>
        </div>
        <p class="lead" style="margin:16px 0 0">Поддержка: ${esc(u.support)}</p>
      </div>
    </div>`;
}

function viewKey() {
  const u = state.user;
  if (!u.active) {
    return `
      <h2 class="page-title">Ключ</h2>
      <div class="card">
        <p>Подписка закончилась. Пополните доступ, чтобы получить ключ.</p>
        <button class="btn" data-nav="pay">Пополнить</button>
      </div>`;
  }
  return `
    <h2 class="page-title">Ваш ключ</h2>
    <p class="lead">${u.active ? "Подписка активна" : ""} · осталось ${u.days_left} дн. · ${esc(u.server_label)}</p>
    <div class="card">
      <h3>Ключ VLESS</h3>
      <p class="lead" style="margin-bottom:12px">Скопируйте ключ или откройте в Happ — добавится как один сервер, не подписка.</p>
      <div class="keybox" id="vless">${esc(u.key)}</div>
      <div class="row" style="margin-top:14px">
        <button class="btn" id="copy-key">Скопировать ключ</button>
        <a class="btn ghost" href="${esc(u.happ_link)}" id="happ">Открыть в Happ</a>
      </div>
    </div>`;
}

function viewHow() {
  return `
    <h2 class="page-title">Как подключиться</h2>
    <div class="card faq">
      <h3>1. Установите Happ</h3>
      <p>
        <a href="https://apps.apple.com/app/happ-proxy-utility/id6504287215" target="_blank" rel="noopener">iPhone / iPad</a>
        ·
        <a href="https://play.google.com/store/apps/details?id=com.happproxy" target="_blank" rel="noopener">Android</a>
      </p>
      <h3>2. Получите ключ</h3>
      <p>В меню нажмите «Ключ», скопируйте ключ или нажмите «Открыть в Happ».</p>
      <h3>3. Включите VPN</h3>
      <p>Импортируйте ключ в Happ как обычный сервер. Включите подключение.</p>
      <h3>4. Включите фрагментирование</h3>
      <p>В настройках Happ включите фрагментирование — так соединение лучше обходит глушилку.</p>
    </div>`;
}

async function viewServers() {
  const data = await api("/api/servers");
  state.servers = data.servers;
  const u = state.user;
  const cooldown = u.can_change_server
    ? ""
    : `<p class="lead">Сменить сервер можно через ${u.change_in_hours}ч ${u.change_in_minutes}м</p>`;
  const list = data.servers
    .map((s) => {
      return `<div class="server ${s.current ? "current" : ""}">
        <div style="display:flex;gap:10px;align-items:center">
          <span class="dot ${s.status}"></span>
          <div>
            <strong>${esc(s.label)}</strong>
            <div class="stat-label">${s.load_pct}% · ${s.count}/${s.limit}${s.current ? " · текущий" : ""}</div>
          </div>
        </div>
        <button class="btn ${s.current || s.full || !u.can_change_server ? "ghost" : ""}" data-server="${esc(s.name)}" ${
        s.current || s.full || !u.can_change_server ? "disabled" : ""
      }>${s.full ? "Полон" : s.current ? "Выбран" : "Выбрать"}</button>
      </div>`;
    })
    .join("");
  return `<h2 class="page-title">Серверы</h2>${cooldown}<div class="card">${list}</div>`;
}

function viewPay() {
  const sbpTariffs = Object.entries(state.meta?.sbp_tariffs || {
    "1m": { title: "1 месяц", price: 100, days: 30 },
    "3m": { title: "3 месяца", price: 250, days: 90 },
    "12m": { title: "12 месяцев", price: 1000, days: 365 },
  });
  const cryptoTariffs = Object.entries(state.meta?.tariffs || {
    "1m": { title: "1 месяц", price: 1, days: 30 },
    "3m": { title: "3 месяца", price: 2.5, days: 90 },
    "12m": { title: "12 месяцев", price: 10, days: 365 },
  });
  const sbpCards = sbpTariffs
    .map(
      ([id, t]) => `<div class="tariff">
        <div class="stat-label">${esc(t.title)}</div>
        <div class="price">${t.price} ₽</div>
        <div class="stat-label">${t.days} дней</div>
        <button class="btn wide" style="margin-top:12px" data-sbp-plan="${id}">Оплатить СБП</button>
      </div>`
    )
    .join("");
  const cryptoCards = cryptoTariffs
    .map(
      ([id, t]) => `<div class="tariff">
        <div class="stat-label">${esc(t.title)}</div>
        <div class="price">${t.price} USDT</div>
        <div class="stat-label">${t.days} дней</div>
        <button class="btn ghost wide" style="margin-top:12px" data-crypto-plan="${id}">Оплатить USDT</button>
      </div>`
    )
    .join("");
  return `
    <h2 class="page-title">Пополнить</h2>
    <p class="lead">Оплачивая, вы принимаете условия сервиса.</p>
    <h3 style="margin:0 0 12px;font-size:16px">СБП</h3>
    <div class="grid cols-3">${sbpCards}</div>
    <h3 style="margin:24px 0 12px;font-size:16px">Другие способы</h3>
    <div class="grid cols-3">${cryptoCards}</div>
    <div class="card" style="margin-top:16px">
      <p class="lead">⭐ Telegram Stars — откройте бота @${esc(state.user.bot_username)}</p>
    </div>
    <div id="pay-box"></div>`;
}

function viewBonus() {
  const u = state.user;
  return `
    <h2 class="page-title">Бонус +7 дней</h2>
    <div class="card">
      <p class="lead">Подпишитесь на канал ${esc(u.channel)} и привяжите Telegram — начислим 7 дней один раз.</p>
      ${u.bonus_used ? `<p class="ok">Бонус уже активирован</p>` : ""}
      ${!u.linked_telegram ? `<p>Сначала привяжите Telegram в разделе «Аккаунт».</p>` : ""}
      <div class="row">
        <a class="btn ghost" href="https://t.me/${esc(u.channel.replace("@", ""))}" target="_blank" rel="noopener">Открыть канал</a>
        <button class="btn" id="claim-bonus" ${u.bonus_used ? "disabled" : ""}>Получить бонус</button>
      </div>
    </div>`;
}

function viewRef() {
  const u = state.user;
  return `
    <h2 class="page-title">Пригласить друга</h2>
    <p class="lead">Друг регистрируется по вашей ссылке — вам +5 дней (до 30 дней суммарно). Уже начислено: ${u.ref_days} дн.</p>
    <div class="grid cols-2">
      <div class="card">
        <h3>Ссылка сайта</h3>
        <div class="keybox">${esc(u.web_ref)}</div>
        <button class="btn" style="margin-top:12px" data-copy="${esc(u.web_ref)}">Скопировать</button>
      </div>
      <div class="card">
        <h3>Ссылка бота</h3>
        <div class="keybox">${esc(u.bot_ref)}</div>
        <button class="btn" style="margin-top:12px" data-copy="${esc(u.bot_ref)}">Скопировать</button>
      </div>
    </div>`;
}

function viewAccount() {
  const u = state.user;
  const linked = u.linked_telegram
    ? `<p class="ok">Telegram привязан${u.tg_username ? " · @" + esc(u.tg_username) : ""} · ID ${u.telegram_id}</p>`
    : `<p class="lead">Аккаунт пока только на сайте. Когда Telegram заработает, привяжите его кодом ниже — подписка и ключ сохранятся.</p>
       <button class="btn" id="make-code">Получить код привязки</button>
       <div id="code-box"></div>`;
  return `
    <h2 class="page-title">Мой аккаунт</h2>
    <div class="card">
      <p>Логин: <strong>${esc(u.web_username)}</strong></p>
      <p>Сервер: ${esc(u.server_label)}</p>
      <p>Осталось дней: ${u.days_left}</p>
      ${linked}
      <div class="row" style="margin-top:12px">
        <button class="btn" data-nav="pay">Пополнить</button>
        <button class="btn ghost" data-nav="terms">Соглашение</button>
        <button class="btn ghost" data-nav="privacy">Конфиденциальность</button>
      </div>
    </div>`;
}

function viewFaq() {
  const u = state.user;
  return `
    <h2 class="page-title">Вопросы и поддержка</h2>
    <div class="card faq">
      <h3>Нет Happ на iOS?</h3>
      <p>Смените регион App Store.</p>
      <h3>Плохая скорость?</h3>
      <p>В Happ включите TUN. Remote DNS: https://1.1.1.1/dns-query · Direct DNS: 1.1.1.1</p>
      <h3>Ошибка добавления ключа?</h3>
      <p>Перезапустите Happ и импортируйте ключ заново.</p>
      <h3>Проблемы на ПК?</h3>
      <p>Запускайте от имени администратора, режим службы: Системный VPN.</p>
      <h3>Не работает TikTok?</h3>
      <p>Очистите кэш → закройте TikTok → подождите 10 секунд → зайдите с VPN.</p>
      <p>Поддержка: ${esc(u.support)}</p>
      <div class="row">
        <button class="btn ghost" data-nav="terms">Соглашение</button>
        <button class="btn ghost" data-nav="privacy">Конфиденциальность</button>
      </div>
    </div>`;
}

async function viewLegal(kind) {
  const data = await api("/api/legal/" + kind);
  return `<h2 class="page-title">${esc(data.title)}</h2><div class="card legal">${esc(data.text)}</div>`;
}

async function openLegal(kind) {
  const data = await api("/api/legal/" + kind);
  app.innerHTML = `<div class="auth-wrap"><div class="card" style="width:min(720px,100%)">
    <h2 class="page-title">${esc(data.title)}</h2>
    <div class="legal">${esc(data.text)}</div>
    <button class="btn" id="back-auth" style="margin-top:16px">Назад</button>
  </div></div>`;
  document.getElementById("back-auth").onclick = render;
}

function viewAdmin() {
  return `
    <h2 class="page-title">Админ</h2>
    <div class="card">
      <div class="field"><label>Telegram ID</label><input id="adm-id" placeholder="123456789"></div>
      <div class="field"><label>Дни (+ или −)</label><input id="adm-days" placeholder="30"></div>
      <div class="row">
        <button class="btn" id="adm-add">Начислить</button>
        <button class="btn ghost" id="adm-time">Проверить срок</button>
      </div>
      <p class="msg" id="adm-msg"></p>
    </div>`;
}

function bindPage() {
  const page = document.getElementById("page");
  page.querySelectorAll("[data-nav]").forEach((btn) => {
    btn.onclick = () => {
      state.view = btn.dataset.nav;
      render();
    };
  });
  page.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.onclick = async () => {
      await navigator.clipboard.writeText(btn.dataset.copy);
      toast("Скопировано");
    };
  });
  const copyKey = document.getElementById("copy-key");
  if (copyKey) {
    copyKey.onclick = async () => {
      await navigator.clipboard.writeText(state.user.key || "");
      toast("Ключ скопирован");
    };
  }
  page.querySelectorAll("[data-server]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        state.user = await api("/api/servers/change", {
          method: "POST",
          body: JSON.stringify({ server: btn.dataset.server }),
        });
        toast("Сервер изменён, ключ обновлён");
        state.view = "key";
        render();
      } catch (err) {
        toast(err.message);
      }
    };
  });
  page.querySelectorAll("[data-sbp-plan]").forEach((btn) => {
    btn.onclick = () => startPay(btn.dataset.sbpPlan, "sbp");
  });
  page.querySelectorAll("[data-crypto-plan]").forEach((btn) => {
    btn.onclick = () => startPay(btn.dataset.cryptoPlan, "crypto");
  });
  const bonus = document.getElementById("claim-bonus");
  if (bonus) {
    bonus.onclick = async () => {
      try {
        state.user = await api("/api/bonus", { method: "POST", body: "{}" });
        toast("Бонус активирован, +7 дней");
        render();
      } catch (err) {
        toast(err.message);
      }
    };
  }
  const makeCode = document.getElementById("make-code");
  if (makeCode) {
    makeCode.onclick = async () => {
      try {
        const data = await api("/api/account/link-code", { method: "POST", body: "{}" });
        document.getElementById("code-box").innerHTML = `
          <div class="code">${esc(data.code)}</div>
          <p class="lead">В боте @${esc(state.user.bot_username)} отправьте:</p>
          <div class="keybox">${esc(data.command)}</div>
          <button class="btn" style="margin-top:12px" data-copy="${esc(data.command)}">Скопировать команду</button>`;
        document.querySelector("#code-box [data-copy]").onclick = async () => {
          await navigator.clipboard.writeText(data.command);
          toast("Команда скопирована");
        };
      } catch (err) {
        toast(err.message);
      }
    };
  }
  const admAdd = document.getElementById("adm-add");
  if (admAdd) {
    admAdd.onclick = async () => {
      const box = document.getElementById("adm-msg");
      try {
        const data = await api("/api/admin/adddays", {
          method: "POST",
          body: JSON.stringify({
            telegram_id: Number(document.getElementById("adm-id").value),
            days: Number(document.getElementById("adm-days").value),
          }),
        });
        box.className = "ok";
        box.textContent = `Готово. Осталось дней: ${data.days_left}`;
      } catch (err) {
        box.className = "msg";
        box.textContent = err.message;
      }
    };
    document.getElementById("adm-time").onclick = async () => {
      const box = document.getElementById("adm-msg");
      try {
        const id = Number(document.getElementById("adm-id").value);
        const data = await api("/api/admin/time/" + id);
        box.className = "ok";
        box.textContent = data.days_left === 0 ? "Подписка истекла" : `Осталось дней: ${data.days_left}`;
      } catch (err) {
        box.className = "msg";
        box.textContent = err.message;
      }
    };
  }
}

async function startPay(plan, method = "sbp") {
  const box = document.getElementById("pay-box");
  box.innerHTML = `<div class="card" style="margin-top:16px"><p>Создаём счёт…</p></div>`;
  const endpoint = method === "sbp" ? "/api/pay/sbp" : "/api/pay/crypto";
  const currency = method === "sbp" ? "₽" : " USDT";
  try {
    const inv = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ plan }),
    });
    box.innerHTML = `<div class="card" style="margin-top:16px">
      <h3>${esc(inv.title)} · ${inv.price}${currency}</h3>
      <p class="lead">После оплаты доступ начислится автоматически. Можно не закрывать эту страницу.</p>
      <a class="btn" href="${esc(inv.pay_url)}" target="_blank" rel="noopener">${method === "sbp" ? "Оплатить СБП" : "Оплатить"}</a>
      <p class="stat-label" id="pay-wait" style="margin-top:12px">Ожидаем оплату…</p>
    </div>`;
    pollPay(inv.invoice_id);
  } catch (err) {
    box.innerHTML = `<div class="card" style="margin-top:16px"><p class="msg">${esc(err.message)}</p></div>`;
  }
}

async function pollPay(invoiceId) {
  for (let i = 0; i < 80; i++) {
    await new Promise((r) => setTimeout(r, 4000));
    try {
      const data = await api("/api/pay/status/" + invoiceId);
      if (data.paid) {
        state.user = data.user;
        toast("Оплата получена");
        state.view = "home";
        render();
        return;
      }
    } catch {
      /* keep waiting */
    }
  }
}

async function boot() {
  try {
    state.meta = await api("/api/meta");
    state.user = state.meta.user;
  } catch {
    state.meta = { tariffs: {} };
  }
  render();
}

boot();
