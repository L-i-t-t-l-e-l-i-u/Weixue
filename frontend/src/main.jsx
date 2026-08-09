import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import StudentWindow from './pages/StudentWindow';
import './index.css';

function Root() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  const match = hash.match(/^#\/student\/(\d+)/);
  if (match) {
    return (
      <React.StrictMode>
        <StudentWindow studentId={parseInt(match[1], 10)} />
      </React.StrictMode>
    );
  }
  return (
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<Root />);
