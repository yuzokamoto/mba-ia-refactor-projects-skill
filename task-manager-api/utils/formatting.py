"""Formatação compartilhada pelas estatísticas."""


def percentage(part, total):
    return round((part / total) * 100, 2) if total else 0
