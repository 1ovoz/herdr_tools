import assert from 'node:assert/strict';
import { pageFlow, visiblePages, pageAt, restorePosition, dropSide } from './document-flow.js';

const flow = pageFlow([[400, 500], [800, 400], [500, 1000]], 430, 400, 1);
assert.equal(flow.pages[0].height, 500);
assert.equal(flow.pages[1].height, 200);
assert.equal(pageAt(flow, 550), 1);
assert.deepEqual(visiblePages(flow, 510, 260), [0, 1, 2]);
const next = pageFlow([[400, 500], [800, 400]], 430, 140, 1.5);
assert.equal(restorePosition(next, 1, .5), next.pages[1].top + next.pages[1].height / 2);
assert.equal(restorePosition(next, 99, 1), next.maxY);
const bounds = {left: 260, right: 1050, top: 60, bottom: 750};
assert.equal(dropSide({x: 400, y: 350},bounds), 'left');
assert.equal(dropSide({x: 800, y: 350},bounds), 'right');
assert.equal(dropSide({x: 1100, y: 350},bounds), null);
assert.equal(dropSide({x: 400, y: 20},bounds), null);
console.log('Continuous page placement and split target tests passed');
