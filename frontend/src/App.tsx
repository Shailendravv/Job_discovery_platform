import React from "react";
import { AppContextProvider, useApp } from "@/context/AppContext";
import { Layout } from "@/components/layout/Layout";
import { DashboardView } from "@/features/dashboard/DashboardView";
import { ResumesView } from "@/features/resumes/ResumesView";
import { ApplicationsView } from "@/features/applications/ApplicationsView";

const MainContent: React.FC = () => {
  const { activeTab } = useApp();

  switch (activeTab) {
    case "Dashboard":
      return <DashboardView />;
    case "Resumes":
      return <ResumesView />;
    case "Applications":
      return <ApplicationsView />;
    default:
      return <DashboardView />;
  }
};

function App() {
  return (
    <AppContextProvider>
      <Layout>
        <MainContent />
      </Layout>
    </AppContextProvider>
  );
}

export default App;
