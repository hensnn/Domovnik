import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Checkbox, Field, Input, Modal, errorMessage } from "./ui";

/**
 * Dialog „Duplikovat“ pro umístění a kategorie: název kopie (prázdný = automaticky
 * „Název (kopie)“) a volba, zda zkopírovat i podřízené položky.
 */
export function DuplicateDialog({
  title,
  sourceName,
  hasChildren,
  childrenLabel,
  hint,
  onSubmit,
  onClose,
}: {
  title: string;
  sourceName: string;
  hasChildren: boolean;
  childrenLabel: string;
  hint: string;
  onSubmit: (body: { name?: string; include_children: boolean }) => Promise<void>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [children, setChildren] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await onSubmit({
        ...(name.trim() ? { name: name.trim() } : {}),
        include_children: hasChildren ? children : false,
      });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title={title}>
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-500">{hint}</p>
        <Field label={t("duplicate.name")}>
          {(id) => (
            <Input
              id={id}
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`${sourceName} ${t("items.copySuffix")}`}
            />
          )}
        </Field>
        {hasChildren && (
          <Checkbox label={childrenLabel} checked={children} onChange={setChildren} />
        )}
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {t("duplicate.submit")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
