export class ManualActionCoordinator {
  constructor({ cancelPlayback, isBusy, execute, onQueued = () => {}, onQueueFull = () => {} }) {
    this.cancelPlayback = cancelPlayback;
    this.isBusy = isBusy;
    this.execute = execute;
    this.onQueued = onQueued;
    this.onQueueFull = onQueueFull;
    this.pending = null;
    this.running = false;
  }

  getState() {
    return {
      running: this.running,
      pending: this.pending ? { ...this.pending.action } : null,
    };
  }

  request(action) {
    this.cancelPlayback();
    if (this.running || this.isBusy()) {
      if (!this.pending) {
        let resolveRequest;
        let rejectRequest;
        const promise = new Promise((resolve, reject) => {
          resolveRequest = resolve;
          rejectRequest = reject;
        });
        this.pending = {
          action: { ...action },
          resolve: resolveRequest,
          reject: rejectRequest,
          promise,
        };
        this.onQueued(action);
        return promise;
      }
      this.onQueueFull(action, this.pending.action);
      return this.pending.promise;
    }
    return this._run(action);
  }

  async _run(action) {
    this.running = true;
    try {
      return await this.execute({ ...action });
    } finally {
      this.running = false;
      if (!this.isBusy()) {
        await this.flush();
      }
    }
  }

  async flush() {
    if (this.running || this.isBusy() || !this.pending) {
      return null;
    }
    const pending = this.pending;
    this.pending = null;
    try {
      const result = await this._run(pending.action);
      pending.resolve(result);
      return result;
    } catch (error) {
      pending.reject(error);
      return null;
    }
  }

  clear(result = null) {
    if (this.pending) {
      this.pending.resolve(result);
      this.pending = null;
    }
  }
}
