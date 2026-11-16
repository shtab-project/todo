// Временное хранилище интерфейса. HTTP API задач будет подключён отдельно.
function createId() {
  if (typeof globalThis.crypto.randomUUID === 'function') return globalThis.crypto.randomUUID();
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}

export const statuses = [
  { id: 'new', title: 'Новые' },
  { id: 'in_progress', title: 'В работе' },
  { id: 'done', title: 'Готово' },
];

export function validDueDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

// В 0.1.0 примеры сохранялись как обычные задачи. Убираем только исходные карточки.
const legacyExamples = [
  ['Записать идеи для заметок', 'Собрать мысли в одном месте, чтобы ничего не потерялось.', 'new', false],
  ['Наметить три главных дела на неделю', 'Оставить достаточно времени на непредвиденное.', 'new', true],
  ['Разобрать входящие', '', 'new', false],
  ['Попробовать доску задач', 'Перетащите карточку в соседнюю колонку или измените статус в редакторе.', 'in_progress', true],
  ['Проверить интерфейс на телефоне', 'Переключиться на список и создать небольшую задачу.', 'in_progress', false],
  ['Собрать всё в одном месте', 'Первый шаг уже сделан.', 'done', true],
];

function isUnchangedExample(task, userId) {
  return !task.due_date && task.created_at === task.updated_at && task.author_id === userId
    && legacyExamples.some(([title, description, status, assignedToSelf]) => (
      task.title === title && task.description === description && task.status === status
      && task.assignee_id === (assignedToSelf ? userId : null)
    ));
}

function validTask(task) {
  return task && typeof task.id === 'string' && typeof task.title === 'string'
    && task.title.trim().length > 0 && task.title.length <= 200
    && typeof task.description === 'string' && typeof task.author_id === 'string'
    && (task.assignee_id === null || typeof task.assignee_id === 'string')
    && statuses.some((status) => status.id === task.status)
    && (task.due_date == null || validDueDate(task.due_date))
    && Number.isFinite(Date.parse(task.created_at)) && Number.isFinite(Date.parse(task.updated_at));
}

export class TaskStore {
  constructor(user, scope = 'private') {
    this.user = user;
    this.scope = scope;
    this.key = scope === 'private' ? `shtab.todo.preview.v1.${user.id}` : `shtab.todo.shared.${user.id}`;
    this.warning = '';
    this.tasks = [];
    this.view = matchMedia('(max-width: 640px)').matches ? 'list' : 'board';
    try {
      const saved = localStorage.getItem(this.key);
      if (saved) {
        const data = JSON.parse(saved);
        if (!Array.isArray(data.tasks) || !data.tasks.every(validTask)
          || new Set(data.tasks.map((task) => task.id)).size !== data.tasks.length) {
          throw new Error('Invalid saved tasks');
        }
        this.tasks = data.legacyExamplesRemoved === true
          ? data.tasks
          : data.tasks.filter((task) => !isUnchangedExample(task, user.id));
        if (['list', 'board'].includes(data.view)) this.view = data.view;
        if (data.legacyExamplesRemoved !== true) this.persist();
      } else {
        this.persist();
      }
    } catch {
      this.tasks = [];
      this.warning = 'Не удалось прочитать сохранённые задачи. Изменения доступны только до закрытия страницы.';
      this.memoryOnly = true;
    }
  }

  async request(path, method = 'GET', payload) {
    const response = await fetch(`/api/plugins/todo${path}`, {
      method, credentials: 'same-origin',
      ...(payload && { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
    });
    if (response.status === 409) throw new Error('Задачи изменились у другого пользователя. Откройте раздел заново и повторите действие.');
    if (response.status === 403) throw new Error('Недостаточно прав для удаления этой задачи.');
    if (!response.ok) throw new Error('Не удалось сохранить или загрузить задачи. Повторите действие.');
    return response.json();
  }

  async load() {
    let snapshot = await this.request(`/workspace/${this.scope}`);
    let imported = false;
    try { imported = localStorage.getItem(`${this.key}.imported`) === '1'; } catch { /* Import is idempotent. */ }
    if (this.scope === 'private' && !imported && this.tasks.length) {
      snapshot = await this.request('/import', 'POST', { tasks: this.tasks });
    }
    if (this.scope === 'private') {
      try { localStorage.setItem(`${this.key}.imported`, '1'); } catch { /* Keep the local backup. */ }
    }
    this.tasks = snapshot.tasks;
    this.revision = snapshot.revision;
  }

  async commit(upsert = [], deleted = []) {
    const snapshot = await this.request(`/workspace/${this.scope}`, 'PATCH', {
      revision: this.revision, upsert, delete: deleted,
    });
    this.tasks = snapshot.tasks;
    this.revision = snapshot.revision;
    this.warning = '';
  }

  persist() {
    if (this.memoryOnly) return;
    try {
      localStorage.setItem(this.key, JSON.stringify({
        tasks: this.tasks, view: this.view, legacyExamplesRemoved: true,
      }));
    } catch {
      this.memoryOnly = true;
      this.warning = 'Хранилище браузера недоступно. Изменения сохранятся только до закрытия страницы.';
    }
  }

  async save(input, id) {
    const title = input.title.trim();
    if (!title || title.length > 200) throw new Error('Введите название длиной до 200 символов.');
    if (!statuses.some((status) => status.id === input.status)) throw new Error('Выберите статус задачи.');
    const dueDate = input.due_date || null;
    if (dueDate !== null && !validDueDate(dueDate)) throw new Error('Укажите корректную дату срока выполнения.');
    const previous = id ? this.tasks.find((task) => task.id === id) : null;
    if (id && !previous) throw new Error('Задача уже удалена.');
    const now = new Date().toISOString();
    const task = {
      ...previous,
      id: previous?.id ?? createId(), title,
      description: input.description.trim(), status: input.status,
      assignee_id: input.assignee_id || null,
      due_date: dueDate,
      author_id: previous?.author_id ?? this.user.id,
      created_at: previous?.created_at ?? now, updated_at: now,
    };
    await this.commit([task]);
    return task;
  }

  async changeStatus(id, status) {
    const task = this.tasks.find((item) => item.id === id);
    if (task) await this.save({ ...task, status }, id);
  }

  async remove(id) {
    await this.commit([], [id]);
  }
}
