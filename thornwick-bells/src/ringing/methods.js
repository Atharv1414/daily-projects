/* Traditional methods, written in place notation. `course` is the known length of a plain course. */
export const METHODS = [
  {
    id: 'plain-hunt-major', name: 'Plain Hunt', stage: 8, notation: 'x18x18x18x18x18x18x18x18', course: 16, level: 'First steps',
    story: 'Everyone walks to the back, then everyone walks to the front. Most new ringers learn this in a month of Tuesdays.',
  },
  {
    id: 'plain-bob-doubles', name: 'Plain Bob Doubles', stage: 5, notation: '&5.1.5.1.5,125', calls: { bob: '145' }, course: 40, level: 'First steps',
    story: 'Plain hunt with one dodge at each lead. Three bobs in the right places ring all 120 orders of five bells.',
    touches: [{ name: 'All 120', calls: 'pppbpppbpppb' }],
  },
  {
    id: 'grandsire-doubles', name: 'Grandsire Doubles', stage: 5, notation: '3,&1.5.1.5.1', course: 30, level: 'First steps',
    story: 'Two bells hunt instead of one. Rung in English towers since the seventeenth century.',
  },
  {
    id: 'stedman-doubles', name: 'Stedman Doubles', stage: 5, notation: '3.1.5.3.1.3.1.3.5.1.3.1', course: 60, level: 'Getting harder',
    story: 'A principle: every bell does the same work, and nobody is the treble. Three bells turn on the front while pairs dodge behind.',
  },
  {
    id: 'plain-bob-minor', name: 'Plain Bob Minor', stage: 6, notation: '&x16x16x16,12', calls: { bob: '14', single: '1234' }, course: 60, level: 'First steps',
    story: 'The method most ringers meet first on six. The whole course is five leads of twelve.',
    touches: [
      { name: 'A 120 with four bobs', calls: 'pppbbpppbb' },
      { name: 'A 180 with three bobs', calls: 'ppppbppppbppppb' },
      { name: 'All 720', calls: 'bbpppbppppbbpppbppppbbpppbpppsbbpppbppppbbpppbppppbbpppbppps' },
    ],
  },
  {
    id: 'st-clements-minor', name: "St Clement's Minor", stage: 6, notation: '&x16x36x36,12', calls: { bob: '14', single: '1234' }, course: 60, level: 'Getting harder',
    story: 'Plain Bob at the back with a run of dodges on the front. Good company when the tenor ringer is tired.',
  },
  {
    id: 'kent-minor', name: 'Kent Treble Bob Minor', stage: 6, notation: '&34x34.16x12x16x12x16,16', calls: { bob: '14' }, course: 120, level: 'Getting harder',
    story: 'Here the treble dodges as well. The slow bell stays near the front while everyone else treble bobs past.',
  },
  {
    id: 'cambridge-minor', name: 'Cambridge Surprise Minor', stage: 6, notation: '&x36x14x12x36x14x56,12', calls: { bob: '14', single: '1234' }, course: 120, level: 'A long winter',
    story: 'Cambridge places: hunt up, make thirds, dodge, make fourths, dodge, and come back the same way.',
  },
  {
    id: 'grandsire-triples', name: 'Grandsire Triples', stage: 7, notation: '3,&1.7.1.7.1.7.1', course: 70, level: 'Getting harder',
    story: 'Seven bells changing with the tenor covering behind. The tenor never moves, which is why it sounds so steady.',
  },
  {
    id: 'plain-bob-major', name: 'Plain Bob Major', stage: 8, notation: '&x18x18x18x18,12', calls: { bob: '14', single: '1234' }, course: 112, level: 'Getting harder',
    story: 'All eight bells at work. This is the course that runs down the side of our front page.',
    touches: [{ name: 'A 240 with three bobs', calls: 'ppppbppppbppppb' }, { name: 'A 336 with three bobs', calls: 'ppppppbppppppbppppppb' }],
  },
  {
    id: 'double-norwich-major', name: 'Double Norwich Court Bob Major', stage: 8, notation: '&x14x36x58x18,18', course: 112, level: 'A long winter',
    story: 'Read it upside down and it is the same. Pairs of bells meet in the middle all the way through.',
  },
  {
    id: 'cambridge-major', name: 'Cambridge Surprise Major', stage: 8, notation: '&x38x14x1258x36x14x58x16x78,12', calls: { bob: '14', single: '1234' }, course: 224, level: 'A long winter',
    story: 'Seven leads of thirty-two. Our band has been trying to ring it cleanly since 1987.',
  },
  {
    id: 'yorkshire-major', name: 'Yorkshire Surprise Major', stage: 8, notation: '&x38x14x58x16x12x38x14x78,12', calls: { bob: '14', single: '1234' }, course: 224, level: 'A long winter',
    story: 'Cambridge with smoother work. Often the second surprise method a band learns on eight.',
  },
]

export const STAGE_NAMES = { 5: 'Five bells', 6: 'Six bells', 7: 'Seven bells and a tenor', 8: 'Eight bells' }

export function findMethod(id) {
  return METHODS.find((m) => m.id === id)
}
