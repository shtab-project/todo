import test from 'node:test';
import assert from 'node:assert/strict';
import { isOverdue, deadlineParts, TaskStore } from '../../frontend/store.js';

// Run with TZ=Europe/Moscow to verify UTC persistence and local-time editing.
test('exact deadline, date-only deadline and completed task', () => {
  const task = { due_date: '2026-11-17', due_at: '2026-11-17T15:00:00Z', status: 'new' };
  assert.equal(isOverdue(task, new Date('2026-11-17T14:59:59Z')), false);
  assert.equal(isOverdue(task, new Date('2026-11-17T15:00:00Z')), true);
  assert.equal(isOverdue({ ...task, status: 'done' }, new Date('2026-11-18T15:00:00Z')), false);
  assert.equal(isOverdue({ ...task, due_at: null }, new Date('2026-11-17T20:59:59Z')), false);
  assert.equal(isOverdue({ ...task, due_at: null }, new Date('2026-11-17T21:00:00Z')), true);
  assert.deepEqual(deadlineParts(task), { date: '2026-11-17', time: '18:00' });
});

test('save converts local time to UTC, retains time on status changes and clears it explicitly', async () => {
  const store = Object.create(TaskStore.prototype);
  store.user = { id: 'user' };
  store.tasks = [];
  store.commit = async ([task]) => { store.tasks = [task]; };
  const input = { title: 'Task', description: '', status: 'new', due_date: '2026-11-17', due_time: '18:00' };
  const created = await store.save(input);
  assert.equal(created.due_at, '2026-11-17T15:00:00.000Z');
  await store.changeStatus(created.id, 'done');
  assert.equal(store.tasks[0].due_at, created.due_at);
  await store.save({ ...input, due_time: '' }, created.id);
  assert.equal(store.tasks[0].due_at, null);
  await assert.rejects(() => store.save({ ...input, due_date: '' }), /укажите дату/);
  await assert.rejects(() => store.save({ ...input, due_time: '25:00' }), /корректное время/);
});
