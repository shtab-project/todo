import { TaskStore, statuses } from './store.js';

const escape = (value = '') => String(value).replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[character]);
const icons = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M3 6h.1M3 12h.1M3 18h.1"/>',
  board: '<rect x="3" y="4" width="7" height="16" rx="2"/><rect x="14" y="4" width="7" height="10" rx="2"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18"/>',
  task: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3h6v4H9zM9 12h6M9 16h4"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]}</svg>`;
const statusOptions = (current) => statuses.map((status) =>
  `<option value="${status.id}" ${status.id === current ? 'selected' : ''}>${status.title}</option>`).join('');

class TodoElement extends HTMLElement {
  connectedCallback() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    const controller = new AbortController();
    this.controller = controller;
    this.search = '';
    this.filter = '';
    this.mine = false;
    this.shadowRoot.replaceChildren();
    this.hidden = true;
    this.start(controller.signal);
  }

  disconnectedCallback() {
    this.controller.abort();
    clearTimeout(this.toastTimer);
  }

  async start(signal) {
    try {
      const response = await fetch('/api/me', { credentials: 'same-origin', signal });
      if (!response.ok) throw new Error('Не удалось загрузить профиль. Обновите страницу.');
      const { user } = await response.json();
      if (signal.aborted) return;
      this.user = user;
      const assignees = await fetch('/api/plugins/todo/assignees', { credentials: 'same-origin', signal });
      if (!assignees.ok) throw new Error('Не удалось загрузить исполнителей. Обновите страницу.');
      this.assignees = await assignees.json();
      this.store = new TaskStore(user);
      await this.store.load();
      if (signal.aborted) return;
      this.shell(signal);
    } catch (error) {
      if (!signal.aborted) this.showError(error.message);
    }
  }

  showError(message) {
    this.shadowRoot.innerHTML = `<p role="alert">${escape(message)}</p>`;
    this.hidden = false;
  }

  shell(signal) {
    this.shadowRoot.innerHTML = `
      <div class="workspace">
        <header class="heading">
          <div><h1>Задачи <span class="total" aria-hidden="true"></span></h1></div>
          <button class="button primary" data-action="create">${icon('plus')}Новая задача</button>
        </header>
        <p class="storage-warning" role="alert" hidden></p>
        <div class="task-scopes" role="group" aria-label="Доступ к задачам"><button data-scope="private">Личные задачи</button><button data-scope="shared">Задачи компании</button></div>
        <div class="board-controls"><div class="toolbar">
          <div class="view-switch" role="group" aria-label="Вид задач">
            <button data-view="board">${icon('board')}Доска</button>
            <button data-view="list">${icon('list')}Список</button>
          </div>
          <label class="search">${icon('search')}<input type="search" placeholder="Найти задачу" aria-label="Найти задачу"></label>
          <select class="status-filter" aria-label="Фильтр по статусу"><option value="">Все статусы</option>${statusOptions('')}</select>
          <button class="mine-button" data-action="mine" aria-pressed="false">Мои задачи</button>
        </div>
        <div class="overview"><span class="progress-label"></span><div class="progress-track" aria-hidden="true"><span></span></div><span class="filtered-count"></span></div></div>
        <div class="tasks-region"></div>
        <p class="board-hint" hidden>Листайте доску в сторону, чтобы увидеть все колонки.</p>
        <p class="toast" role="status" aria-live="polite"></p>
      </div>
      <dialog aria-labelledby="editor-heading"><form novalidate>
        <header class="dialog-header"><h2 id="editor-heading"></h2><button type="button" class="icon-button" data-action="cancel" aria-label="Закрыть">${icon('close')}</button></header>
        <div class="form-body">
          <label>Название <span class="required">*</span><input name="title" maxlength="200" required placeholder="Что нужно сделать?" autocomplete="off"></label>
          <label>Описание<textarea name="description" rows="4" placeholder="Детали, ссылки, мысли — всё, что пригодится"></textarea></label>
          <label>Срок выполнения<input name="due_date" type="date" max="9999-12-31"></label>
          <div class="form-columns"><label>Статус<select name="status">${statusOptions('new')}</select></label>
            <label>Исполнитель<select name="assignee_id">${this.assigneeOptions()}</select></label></div>
          <p class="form-error" role="alert" hidden></p>
          <div class="delete-confirm" hidden><p>Удалить задачу? Отменить это действие не получится.</p><div><button type="button" class="button danger" data-action="confirm-delete">Удалить задачу</button><button type="button" class="button" data-action="keep">Оставить</button></div></div>
        </div>
        <footer class="dialog-footer"><button type="button" class="delete-button" data-action="delete">Удалить</button><span></span><button type="button" class="button" data-action="cancel">Отмена</button><button class="button primary" type="submit">Создать задачу</button></footer>
      </form></dialog>
      <div class="task-menu" role="menu" aria-label="Действия с задачами" hidden></div>
      <dialog class="task-delete-dialog" aria-labelledby="task-delete-heading"><div class="form-body"><h2 id="task-delete-heading">Удалить задачу?</h2><p class="task-delete-name"></p><p>Восстановить её не получится.</p></div><footer class="dialog-footer"><button class="button" data-action="cancel-menu-delete" autofocus>Отмена</button><button class="button danger" data-action="menu-confirm-delete">Удалить задачу</button></footer></dialog>`;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = new URL('./style.css', import.meta.url).href;
    stylesheet.addEventListener('load', () => { this.hidden = false; }, { once: true, signal });
    stylesheet.addEventListener('error', () => this.showError('Не удалось загрузить оформление задач. Обновите страницу.'), { once: true, signal });
    this.shadowRoot.prepend(stylesheet);
    const options = { signal };
    this.shadowRoot.addEventListener('contextmenu', (event) => {
      if (!event.target.closest('.workspace') || event.target.closest('input, textarea, select')) return;
      event.preventDefault();
      this.openMenu(event.target, event.clientX, event.clientY);
    }, options);
    this.shadowRoot.addEventListener('keydown', (event) => {
      const menu = this.shadowRoot.querySelector('.task-menu');
      if (event.key === 'Escape' && !menu.hidden) {
        event.preventDefault(); this.closeMenu(true); return;
      }
      if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
        if (!event.target.closest('.workspace')) return;
        event.preventDefault();
        const rect = event.target.getBoundingClientRect();
        this.openMenu(event.target, rect.left, rect.bottom);
      }
      if (event.target.closest('.task-menu') && ['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const items = [...menu.querySelectorAll('button')];
        const index = items.indexOf(event.target);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
          : (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length;
        items[next].focus();
      }
      if (event.key === 'Tab' && !menu.hidden) this.closeMenu();
    }, options);
    document.addEventListener('pointerdown', (event) => {
      if (!event.composedPath().includes(this.shadowRoot.querySelector('.task-menu'))) this.closeMenu();
    }, options);
    window.addEventListener('resize', () => this.closeMenu(), options);
    document.addEventListener('scroll', () => this.closeMenu(), { ...options, capture: true });
    this.shadowRoot.addEventListener('click', (event) => this.click(event).catch((error) => this.notify(error.message)), options);
    this.shadowRoot.addEventListener('change', (event) => this.change(event).catch((error) => {
      this.renderTasks();
      this.notify(error.message);
    }), options);
    this.shadowRoot.addEventListener('input', (event) => {
      if (event.target.closest('form')) this.shadowRoot.querySelector('.form-error').hidden = true;
    }, options);
    this.shadowRoot.querySelector('input[type="search"]').addEventListener('input', (event) => {
      this.search = event.target.value;
      this.renderTasks();
    }, options);
    this.shadowRoot.querySelector('form').addEventListener('submit', (event) => this.save(event), options);
    this.shadowRoot.addEventListener('dragstart', (event) => this.dragStart(event), options);
    this.shadowRoot.addEventListener('dragover', (event) => this.dragOver(event), options);
    this.shadowRoot.addEventListener('drop', (event) => this.drop(event).catch((error) => {
      this.clearDrag();
      this.notify(error.message);
    }), options);
    this.shadowRoot.addEventListener('dragend', () => this.clearDrag(), options);
    this.renderTasks();
  }

  visibleTasks() {
    const query = this.search.trim().toLocaleLowerCase('ru');
    return this.store.tasks.filter((task) => (!this.filter || task.status === this.filter)
      && (!this.mine || task.assignee_id === this.user.id)
      && (!query || `${task.title} ${task.description}`.toLocaleLowerCase('ru').includes(query)));
  }

  renderTasks() {
    this.closeMenu();
    const root = this.shadowRoot;
    root.querySelectorAll('[data-scope]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.scope === this.store.scope)));
    const tasks = this.visibleTasks();
    const total = this.store.tasks.length;
    const done = this.store.tasks.filter((task) => task.status === 'done').length;
    root.querySelector('.view-switch').dataset.view = this.store.view;
    root.querySelector('.total').textContent = total;
    root.querySelector('.progress-label').textContent = total ? `${done} из ${total} выполнено` : 'Начните с первой задачи';
    root.querySelector('.progress-track span').style.width = `${total ? done / total * 100 : 0}%`;
    root.querySelector('.filtered-count').textContent = tasks.length !== total ? `Показано: ${tasks.length}` : '';
    root.querySelectorAll('[data-view]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.view === this.store.view)));
    root.querySelector('.mine-button').setAttribute('aria-pressed', String(this.mine));
    const warning = root.querySelector('.storage-warning');
    warning.textContent = this.store.warning;
    warning.hidden = !this.store.warning;
    root.querySelector('.board-hint').hidden = this.store.view !== 'board' || !tasks.length;
    const region = root.querySelector('.tasks-region');
    if (!tasks.length) {
      const filtered = Boolean(this.search || this.filter || this.mine);
      region.innerHTML = `<div class="empty">${icon(filtered ? 'search' : 'task')}<h2>${filtered ? 'Ничего не нашлось' : 'Пока ни одной задачи'}</h2><p>${filtered ? 'Попробуйте другой запрос или уберите фильтры.' : 'Запишите первое дело — и освободите для него место в голове.'}</p><button class="button ${filtered ? '' : 'primary'}" data-action="${filtered ? 'reset-filters' : 'create'}">${filtered ? 'Сбросить фильтры' : 'Создать задачу'}</button></div>`;
    } else if (this.store.view === 'board') {
      region.innerHTML = `<div class="board" aria-label="Доска задач">${statuses.map((status) => {
        const column = tasks.filter((task) => task.status === status.id);
        return `<section class="column ${status.id}" data-column="${status.id}" aria-label="${status.title}">
          <header class="column-header"><h2>${status.title}</h2><span class="column-count">${column.length}</span><button class="icon-button" data-action="create" data-status="${status.id}" aria-label="Добавить задачу: ${status.title}">${icon('plus')}</button></header>
          <div class="column-tasks">${column.map((task) => this.card(task)).join('')}</div>
          </section>`;
      }).join('')}</div>`;
    } else {
      region.innerHTML = `<ul class="task-list" aria-label="Список задач">${tasks.map((task) => this.row(task)).join('')}</ul>`;
    }
  }

  assignee(task) {
    const person = this.assignees.find((user) => user.id === task.assignee_id);
    return person ? person.name || person.username : task.assignee_id ? 'Пользователь недоступен' : '';
  }

  assigneeOptions(task) {
    const users = [...this.assignees].sort((a, b) => Number(b.id === this.user.id) - Number(a.id === this.user.id));
    const options = users.map((user) => `<option value="${escape(user.id)}">${user.id === this.user.id ? 'Я — ' : ''}${escape(user.name || user.username)} (@${escape(user.username)})</option>`).join('');
    const missing = task?.assignee_id && !users.some((user) => user.id === task.assignee_id);
    return `<option value="">Не назначен</option>${options}${missing ? `<option value="${escape(task.assignee_id)}">Пользователь недоступен</option>` : ''}`;
  }

  initials(name) {
    const [first, last] = name.trim().split(/\s+/, 2);
    return (last ? first[0] + last[0] : first.slice(0, 2)).toUpperCase();
  }

  statusSelect(task) {
    return `<select class="task-status ${task.status}" data-task-status="${escape(task.id)}" aria-label="Статус: ${escape(task.title)}">${statusOptions(task.status)}</select>`;
  }

  card(task) {
    const assignee = this.assignee(task);
    return `<article class="task-card ${task.status}" draggable="true" data-task="${escape(task.id)}">
      <button class="card-content" data-action="edit" data-id="${escape(task.id)}"><h3>${escape(task.title)}</h3>${task.description ? `<p>${escape(task.description)}</p>` : ''}</button>
      <footer>${this.deadline(task)}<span class="avatar ${assignee ? 'assigned' : ''}" title="${escape(assignee || 'Без исполнителя')}">${assignee ? escape(this.initials(assignee)) : '—'}</span></footer></article>`;
  }

  deadline(task) {
    if (!task.due_date) return '';
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    const overdue = task.status !== 'done' && task.due_date < today;
    const date = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short', year: 'numeric' })
      .format(new Date(`${task.due_date}T00:00:00`));
    return `<time class="task-deadline ${overdue ? 'overdue' : ''}" datetime="${escape(task.due_date)}" title="Срок выполнения">${icon('calendar')}${overdue ? 'Просрочено · ' : 'До '}${escape(date)}</time>`;
  }

  row(task) {
    const assignee = this.assignee(task);
    const date = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short' }).format(new Date(task.updated_at));
    return `<li class="task-row ${task.status}"><button class="complete-button" data-action="complete" data-id="${escape(task.id)}" aria-label="${task.status === 'done' ? 'Вернуть в новые' : 'Завершить'}: ${escape(task.title)}">${task.status === 'done' ? icon('check') : ''}</button>
      <button class="row-content" data-action="edit" data-id="${escape(task.id)}"><span class="row-title">${escape(task.title)}</span>${task.description ? `<span class="row-description">${escape(task.description)}</span>` : ''}${this.deadline(task)}</button>
      <div class="row-details">
        ${this.statusSelect(task)}
        <span class="row-assignee" title="${escape(assignee || 'Без исполнителя')}">
          ${assignee ? `<span class="avatar assigned" aria-hidden="true">${escape(this.initials(assignee))}</span>` : ''}
          <span class="assignee-name">${escape(assignee || 'Без исполнителя')}</span>
        </span>
        <time class="row-date" datetime="${escape(task.updated_at)}" title="Дата обновления">${icon('calendar')}${date}</time>
      </div></li>`;
  }

  async click(event) {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.scope && button.dataset.scope !== this.store.scope) {
      if (this.switching) return;
      this.switching = true;
      try {
        const store = new TaskStore(this.user, button.dataset.scope);
        await store.load();
        this.store = store;
        this.search = ''; this.filter = ''; this.mine = false;
        this.shadowRoot.querySelector('input[type="search"]').value = '';
        this.shadowRoot.querySelector('.status-filter').value = '';
        this.renderTasks();
      } finally { this.switching = false; }
      return;
    }
    if (button.dataset.view) {
      this.store.view = button.dataset.view;
      this.store.persist();
      this.renderTasks();
      return;
    }
    const action = button.dataset.action;
    this.closeMenu();
    if (action === 'menu-delete') {
      const task = this.store.tasks.find((item) => item.id === button.dataset.id);
      if (!task || !this.canDelete(task)) return;
      this.pendingDeleteId = task.id;
      const dialog = this.shadowRoot.querySelector('.task-delete-dialog');
      dialog.querySelector('.task-delete-name').textContent = task.title;
      dialog.showModal();
    }
    if (action === 'cancel-menu-delete') this.shadowRoot.querySelector('.task-delete-dialog').close();
    if (action === 'menu-confirm-delete' && this.pendingDeleteId) {
      if (button.disabled) return;
      button.disabled = true;
      try {
        await this.store.remove(this.pendingDeleteId);
        this.shadowRoot.querySelector('.task-delete-dialog').close();
        this.pendingDeleteId = null;
        this.renderTasks();
        this.notify('Задача удалена');
      } finally { button.disabled = false; }
    }
    if (action === 'create') this.openEditor(null, button.dataset.status || 'new');
    if (action === 'edit') this.openEditor(button.dataset.id);
    if (action === 'cancel') this.shadowRoot.querySelector('dialog').close();
    if (action === 'mine') { this.mine = !this.mine; this.renderTasks(); }
    if (action === 'reset-filters') {
      this.search = ''; this.filter = ''; this.mine = false;
      this.shadowRoot.querySelector('input[type="search"]').value = '';
      this.shadowRoot.querySelector('.status-filter').value = '';
      this.renderTasks();
    }
    if (action === 'complete') {
      const task = this.store.tasks.find((item) => item.id === button.dataset.id);
      await this.store.changeStatus(task.id, task.status === 'done' ? 'new' : 'done');
      this.renderTasks();
      this.notify(task.status === 'done' ? 'Задача возвращена в новые' : 'Задача выполнена');
    }
    if (action === 'delete' || action === 'keep') this.shadowRoot.querySelector('.delete-confirm').hidden = action === 'keep';
    if (action === 'confirm-delete' && this.editingId) {
      await this.store.remove(this.editingId);
      this.shadowRoot.querySelector('dialog').close();
      this.renderTasks();
      this.notify('Задача удалена');
    }
  }

  async change(event) {
    if (event.target.matches('.status-filter')) {
      this.filter = event.target.value;
      this.renderTasks();
    }
    const id = event.target.dataset.taskStatus;
    if (id) {
      await this.store.changeStatus(id, event.target.value);
      this.renderTasks();
      this.shadowRoot.querySelector(`[data-task-status="${CSS.escape(id)}"]`)?.focus();
      this.notify('Статус изменён');
    }
  }

  openEditor(id, status = 'new') {
    const task = this.store.tasks.find((item) => item.id === id);
    this.editingId = task?.id;
    const dialog = this.shadowRoot.querySelector('dialog');
    const form = dialog.querySelector('form');
    form.reset();
    form.elements.title.value = task?.title ?? '';
    form.elements.description.value = task?.description ?? '';
    form.elements.due_date.value = task?.due_date ?? '';
    form.elements.status.value = task?.status ?? status;
    form.elements.assignee_id.innerHTML = this.assigneeOptions(task);
    form.elements.assignee_id.value = task?.assignee_id ?? '';
    dialog.querySelector('h2').textContent = task ? 'Задача' : 'Новая задача';
    dialog.querySelector('[type="submit"]').textContent = task ? 'Сохранить изменения' : 'Создать задачу';
    dialog.querySelector('[data-action="delete"]').hidden = !task || !this.canDelete(task);
    dialog.querySelector('.delete-confirm').hidden = true;
    dialog.querySelector('.form-error').hidden = true;
    dialog.showModal();
    form.elements.title.focus();
  }

  async save(event) {
    event.preventDefault();
    const form = event.target;
    const submit = form.querySelector('[type="submit"]');
    if (submit.disabled) return;
    submit.disabled = true;
    try {
      await this.store.save(Object.fromEntries(new FormData(form)), this.editingId);
      this.shadowRoot.querySelector('dialog').close();
      this.renderTasks();
      this.notify(this.editingId ? 'Изменения сохранены' : 'Задача создана');
    } catch (error) {
      const message = form.querySelector('.form-error');
      message.textContent = error.message;
      message.hidden = false;
      form.elements.title.focus();
    } finally {
      submit.disabled = false;
    }
  }

  notify(message) {
    clearTimeout(this.toastTimer);
    this.shadowRoot.querySelector('.toast').textContent = message;
    this.toastTimer = setTimeout(() => { this.shadowRoot.querySelector('.toast').textContent = ''; }, 3500);
  }

  canDelete(task) {
    return task.author_id === this.user.id || this.user.is_admin || this.user.is_trusted;
  }

  closeMenu(restoreFocus = false) {
    const menu = this.shadowRoot.querySelector('.task-menu');
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    if (restoreFocus) this.menuTrigger?.focus();
  }

  openMenu(target, x, y) {
    const card = target.closest('[data-task], .task-row');
    const id = card?.dataset.task || card?.querySelector('[data-action="edit"]')?.dataset.id;
    const task = this.store.tasks.find((item) => item.id === id);
    const status = task?.status || target.closest('[data-column]')?.dataset.column || 'new';
    const menu = this.shadowRoot.querySelector('.task-menu');
    this.menuTrigger = target.closest('button') || this.shadowRoot.querySelector('[data-action="create"]');
    menu.innerHTML = `<button role="menuitem" data-action="create" data-status="${escape(status)}">${icon('plus')}Создать задачу</button>
      ${task ? `<button role="menuitem" data-action="edit" data-id="${escape(task.id)}">${icon('task')}Открыть задачу</button>` : ''}
      ${task && this.canDelete(task) ? `<button role="menuitem" class="menu-danger" data-action="menu-delete" data-id="${escape(task.id)}">${icon('close')}Удалить задачу</button>` : ''}`;
    menu.hidden = false;
    const rect = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - rect.width - 8))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - rect.height - 8))}px`;
    menu.querySelector('button').focus({ preventScroll: true });
  }

  dragStart(event) {
    const card = event.target.closest('[data-task]');
    if (!card || event.target.closest('select')) { event.preventDefault(); return; }
    this.draggedId = card.dataset.task;
    event.dataTransfer.setData('text/plain', this.draggedId);
    event.dataTransfer.effectAllowed = 'move';
    card.classList.add('dragging');
  }

  dragOver(event) {
    const column = event.target.closest('[data-column]');
    if (!column || !this.draggedId) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    this.shadowRoot.querySelectorAll('.drop-target').forEach((item) => item.classList.remove('drop-target'));
    column.classList.add('drop-target');
  }

  async drop(event) {
    const column = event.target.closest('[data-column]');
    if (!column || !this.draggedId) return;
    event.preventDefault();
    await this.store.changeStatus(this.draggedId, column.dataset.column);
    this.clearDrag();
    this.renderTasks();
    this.notify('Задача перемещена');
  }

  clearDrag() {
    this.draggedId = null;
    this.shadowRoot.querySelectorAll('.drop-target, .dragging').forEach((item) => item.classList.remove('drop-target', 'dragging'));
  }
}

if (!customElements.get('shtab-todo')) {
  customElements.define('shtab-todo', TodoElement);
}
