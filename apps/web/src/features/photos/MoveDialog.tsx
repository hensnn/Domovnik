import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useLocations } from "../../api/hooks";
import { LocationSelect } from "../../components/Pickers";
import { Button, Checkbox, Field, Input, Modal } from "../../components/ui";
import { parsePath } from "../../lib/photos";
import type { Move } from "../../lib/reviewGroups";
import { CategoryPathField } from "./DetectionRow";

/**
 * Hromadný přesun nalezených věcí: nová kategorie a / nebo nové umístění (existující, nebo
 * nové zadané cestou). Mění jen koncept kontroly; zapíše se až po závěrečném uložení.
 */
export default function MoveDialog({
  count,
  onApply,
  onClose,
}: {
  count: number;
  onApply: (move: Move) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { data: locs = [] } = useLocations();
  const [changeCat, setChangeCat] = useState(true);
  const [catPath, setCatPath] = useState<string[]>([]);
  const [changeLoc, setChangeLoc] = useState(true);
  const [newLoc, setNewLoc] = useState(false);
  const [locId, setLocId] = useState<string | null>(null);
  const [locText, setLocText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const apply = () => {
    const move: Move = {};
    if (changeCat) {
      if (!catPath.length) return setError(t("photos.move.needCategory"));
      move.categoryPath = catPath;
    }
    if (changeLoc) {
      if (newLoc) {
        const path = parsePath(locText);
        if (!path.length) return setError(t("photos.move.needLocation"));
        move.location = { path, label: path.join(" › ") };
      } else {
        if (!locId) return setError(t("photos.move.needLocation"));
        move.location = {
          id: locId,
          label: locs.find((l) => l.id === locId)?.full_name ?? t("photos.locationChosen"),
        };
      }
    }
    if (!move.categoryPath && !move.location) return setError(t("photos.move.nothing"));
    onApply(move);
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={t("photos.move.title", { count })}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" onClick={apply}>
            {t("photos.move.submit")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-500">{t("photos.move.hint")}</p>

        <fieldset className="space-y-2">
          <Checkbox
            label={t("photos.move.changeCategory")}
            checked={changeCat}
            onChange={(v) => {
              setChangeCat(v);
              setError(null);
            }}
          />
          {changeCat && (
            <Field label={t("items.category")}>
              {(id) => <CategoryPathField id={id} value={catPath} onChange={setCatPath} />}
            </Field>
          )}
        </fieldset>

        <fieldset className="space-y-2">
          <Checkbox
            label={t("photos.move.changeLocation")}
            checked={changeLoc}
            onChange={(v) => {
              setChangeLoc(v);
              setError(null);
            }}
          />
          {changeLoc && (
            <>
              {newLoc ? (
                <Field label={t("photos.move.newLocationLabel")}>
                  {(id) => (
                    <Input
                      id={id}
                      value={locText}
                      onChange={(e) => setLocText(e.target.value)}
                      placeholder={t("photos.move.newLocationPlaceholder")}
                    />
                  )}
                </Field>
              ) : (
                <Field label={t("items.location")}>
                  {(id) => (
                    <LocationSelect
                      id={id}
                      value={locId}
                      onChange={setLocId}
                      emptyLabel={t("photos.move.chooseLocation")}
                    />
                  )}
                </Field>
              )}
              <Checkbox
                label={t("photos.move.newLocation")}
                checked={newLoc}
                onChange={(v) => {
                  setNewLoc(v);
                  setError(null);
                }}
              />
            </>
          )}
        </fieldset>

        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
