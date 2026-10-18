import test from 'node:test';
import assert from 'node:assert/strict';
import { loadLib } from './load-lib.mjs';

const { parseOnboarding, onboardingKey, projectTourStage, projectTourStep } = await loadLib('onboarding');
const document = (phase, hasPreview = false) => ({ id: 'document-uuid', phase, hasPreview });
const file = (phase, documents = []) => ({ id: 'analysis-uuid', phase, documents });
const project = (files = [], processingCount = 0) => ({ id: 'project-uuid', files, processingCount });

test('onboarding progress is separate for each user and rejects malformed saved state', () => {
  assert.notEqual(onboardingKey('user-a'), onboardingKey('user-b'));
  for (const raw of [null, '{broken', '[]', 'null']) assert.deepEqual(parseOnboarding(raw), { workspaceDone: false, projectDone: false, projectId: null });
  assert.deepEqual(parseOnboarding('{"workspaceDone":"true","projectDone":1,"projectId":"\u0000"}'), { workspaceDone: false, projectDone: false, projectId: null });
});

test('saved unfinished project resumes, while a completed tour cannot resurrect a stale project', () => {
  assert.deepEqual(parseOnboarding('{"workspaceDone":true,"projectDone":false,"projectId":"project-uuid"}'), { workspaceDone: true, projectDone: false, projectId: 'project-uuid' });
  assert.equal(parseOnboarding('{"projectDone":true,"projectId":"old-project"}').projectId, null);
});

test('a new project starts with upload and uploaded files require a real analysis start', () => {
  assert.equal(projectTourStage(project()), 'upload');
  assert.equal(projectTourStage(project([file('uploaded', [document('uploaded')])])), 'start');
  assert.equal(projectTourStep(project()).number, 1);
});

test('queued and processing archive children keep the guide waiting even at 100 percent', () => {
  assert.equal(projectTourStage(project([file('ready', [{...document('processing'), progress: 100}])])), 'waiting');
  assert.equal(projectTourStage(project([file('ready', [document('queued')])])), 'waiting');
  assert.equal(projectTourStage(project([file('ready', [document('ready', true)])], 1)), 'waiting');
});

test('new uploaded or processing files take priority over an older ready document', () => {
  const older = file('ready', [document('ready', true)]);
  assert.equal(projectTourStage(project([older, file('uploaded')])), 'start');
  assert.equal(projectTourStage(project([older, file('processing')])), 'waiting');
});

test('only an openable document offers the last action; failures and absent preview stay distinct', () => {
  assert.equal(projectTourStage(project([file('ready', [document('ready', true)])])), 'open');
  assert.equal(projectTourStage(project([file('failed', [document('failed')])])), 'failed');
  assert.equal(projectTourStage(project([file('unsupported')])), 'failed');
  assert.equal(projectTourStage(project([file('ready', [document('ready', false)])])), 'unavailable');
  const step = projectTourStep(project([file('ready', [document('ready', true)])]));
  assert.equal(step.number, 3);
  assert.equal(step.target, '[data-onboarding="open-document"]');
});
