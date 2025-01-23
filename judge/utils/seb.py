def is_valid_seb_env(req, contest):
    if not contest.enforce_seb: return True
    # TODO: thêm logic validate digest
    digest = req.headers.get('X-SafeExamBrowser-ConfigKeyHash')
    if digest is not None and digest != "":
        return True
    if req.in_contest:
        req.profile.remove_contest()
    return False