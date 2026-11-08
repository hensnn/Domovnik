import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Drawer } from "../../components/ui";
import AssistantPage from "./AssistantPage";

/**
 * Asistent v postranním panelu – dostupný přímo na stránkách, kde se zakládá struktura
 * (umístění, kategorie), s ukázkami a nápovědou pro dané místo. Změny jen navrhuje
 * a provedou se po potvrzení stejně jako na stránce Asistent.
 */
export default function AssistantDrawer({
  open,
  onClose,
  examples,
  hint,
  contextLocationId,
}: {
  open: boolean;
  onClose: () => void;
  examples: string[];
  hint: string;
  /** Umístění otevřené na stránce; předvyplní „Jsem tady“ v panelu. */
  contextLocationId?: string | null;
}) {
  const { t } = useTranslation();
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2 font-semibold">
          <Sparkles className="size-4 text-brand-600" /> {t("nav.assistant")}
        </span>
      }
    >
      <div className="h-full">
        <AssistantPage
          embedded
          examples={examples}
          hint={hint}
          contextLocationId={contextLocationId}
        />
      </div>
    </Drawer>
  );
}
