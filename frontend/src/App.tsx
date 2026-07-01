import React from "react";
import { Routes, Route } from "react-router-dom";
import { AppContextProvider } from "@/context/AppContext";
import { Layout } from "@/components/layout/Layout";
import { DashboardView } from "@/features/dashboard/DashboardView";
import { DiscoveryView } from "@/features/discovery/DiscoveryView";
import { ResumesView } from "@/features/resumes/ResumesView";
import { ApplicationsView } from "@/features/applications/ApplicationsView";
import { JobDetailsView } from "@/features/job-details/JobDetailsView";

const DashboardPage: React.FC = () => {
  return <DashboardView />;
};

const ResumesPage: React.FC = () => {
  return <ResumesView />;
};

const ApplicationsPage: React.FC = () => {
  return <ApplicationsView />;
};

function App() {
  return (
    <AppContextProvider>
      <Layout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/discovery" element={<DiscoveryView />} />
          <Route path="/jobs/:jobId" element={<JobDetailsView />} />
          <Route path="/resumes" element={<ResumesPage />} />
          <Route path="/applications" element={<ApplicationsPage />} />
        </Routes>
      </Layout>
    </AppContextProvider>
  );
}

export default App;
