import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import AssistantPage from "./features/assistant/AssistantPage";
import CategoriesPage from "./features/categories/CategoriesPage";
import DashboardPage from "./features/dashboard/DashboardPage";
import InventoryPage from "./features/inventory/InventoryPage";
import KnowledgePage from "./features/knowledge/KnowledgePage";
import ItemsPage from "./features/items/ItemsPage";
import LocationsPage from "./features/locations/LocationsPage";
import AddFromPhotoPage from "./features/photos/AddFromPhotoPage";
import ScanPage from "./features/scan/ScanPage";
import SettingsPage from "./features/settings/SettingsPage";
import TagsPage from "./features/tags/TagsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="items" element={<ItemsPage />} />
        <Route path="items/:id" element={<ItemsPage />} />
        <Route path="locations" element={<LocationsPage />} />
        <Route path="locations/:id" element={<LocationsPage />} />
        <Route path="assistant" element={<AssistantPage />} />
        <Route path="add-photo" element={<AddFromPhotoPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="tags" element={<TagsPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="scan" element={<ScanPage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="inventory/:id" element={<InventoryPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<DashboardPage />} />
      </Route>
    </Routes>
  );
}
