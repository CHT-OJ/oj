function hashText(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index++) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function createDeterministicTieKeys(contestants, seed) {
  const shuffled = contestants
    .map((contestant) => {
      const id = String(contestant.participation_id ?? contestant.participationId);
      return {
        id,
        hash: hashText(`${seed}\u0000${id}`),
      };
    })
    .sort((left, right) => left.hash - right.hash || left.id.localeCompare(right.id));

  return new Map(shuffled.map((entry, index) => [entry.id, index]));
}

export function createSourceOrderTieKeys(contestants) {
  return new Map(
    contestants.map((contestant, index) => [
      String(contestant.participation_id ?? contestant.participationId),
      index,
    ]),
  );
}

export function compareContestants(left, right) {
  if (left.isDisqualified !== right.isDisqualified) {
    return left.isDisqualified ? 1 : -1;
  }
  if (left.score !== right.score) {
    return right.score - left.score;
  }
  if (left.cumtime !== right.cumtime) {
    return left.cumtime - right.cumtime;
  }
  if (left.tiebreaker !== right.tiebreaker) {
    return left.tiebreaker - right.tiebreaker;
  }
  return left.tieKey - right.tieKey;
}

function sameDisplayedRank(left, right) {
  return (
    left.score === right.score &&
    left.cumtime === right.cumtime &&
    left.tiebreaker === right.tiebreaker
  );
}

export function rankContestants(contestants) {
  const ordered = [...contestants].sort(compareContestants);
  let displayedRank = 0;
  let previous = null;

  return ordered.map((contestant, index) => {
    if (previous === null || !sameDisplayedRank(previous, contestant)) {
      displayedRank = index + 1;
    }
    previous = contestant;
    return {
      contestantId: contestant.participationId,
      position: index + 1,
      rank: displayedRank,
      score: contestant.score,
      cumtime: contestant.cumtime,
      tiebreaker: contestant.tiebreaker,
      isDisqualified: contestant.isDisqualified,
    };
  });
}
