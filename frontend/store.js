// Временное хранилище интерфейса. HTTP API задач будет подключён отдельно.
export const statuses = [
  { id: 'new', title: 'Новые' },
  { id: 'in_progress', title: 'В работе' },
  { id: 'done', title: 'Готово' },
];

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
  return task.created_at === task.updated_at && task.author_id === userId
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
    && Number.isFinite(Date.parse(task.created_at)) && Number.isFinite(Date.parse(task.updated_at));
}

export class TaskStore {
  constructor(user) {
    this.user = user;
    this.key = `shtab.todo.preview.v1.${user.id}`;
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

  save(input, id) {
    const title = input.title.trim();
    if (!title || title.length > 200) throw new Error('Введите название длиной до 200 символов.');
    if (!statuses.some((status) => status.id === input.status)) throw new Error('Выберите статус задачи.');
    const previous = id ? this.tasks.find((task) => task.id === id) : null;
    if (id && !previous) throw new Error('Задача уже удалена.');
    const now = new Date().toISOString();
    const task = {
      ...previous,
      id: previous?.id ?? crypto.randomUUID(), title,
      description: input.description.trim(), status: input.status,
      assignee_id: input.assignee_id || null,
      author_id: previous?.author_id ?? this.user.id,
      created_at: previous?.created_at ?? now, updated_at: now,
    };
    this.tasks = previous ? this.tasks.map((item) => item.id === id ? task : item) : [task, ...this.tasks];
    this.persist();
    return task;
  }

  changeStatus(id, status) {
    const task = this.tasks.find((item) => item.id === id);
    if (task) this.save({ ...task, status }, id);
  }

  remove(id) {
    this.tasks = this.tasks.filter((task) => task.id !== id);
    this.persist();
  }
}
