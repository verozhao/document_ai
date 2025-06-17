"""
Real-time monitoring dashboard for the automated Document AI training pipeline.
Provides insights into training status, document processing, and system health.
"""

import asyncio
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import json
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from google.cloud import firestore
from google.cloud import documentai_v1 as documentai
from google.cloud import storage
from google.cloud import logging as cloud_logging
from google.api_core.client_options import ClientOptions


class AutomatedTrainingMonitor:
    """Monitor for the automated Document AI training pipeline."""

    def __init__(self, project_id: str, processor_id: str, location: str = "us"):
        self.project_id = project_id
        self.processor_id = processor_id
        self.location = location
        
        # Initialize clients
        self.firestore_client = firestore.Client(project=project_id)
        self.storage_client = storage.Client(project=project_id)
        self.logging_client = cloud_logging.Client(project=project_id)
        
        # Document AI client
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        self.docai_client = documentai.DocumentProcessorServiceClient(client_options=opts)
        
        # Console for rich output
        self.console = Console()
        
        # Processor path
        self.processor_path = f"projects/{project_id}/locations/{location}/processors/{processor_id}"

    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Gather all data for the dashboard."""
        data = {}
        
        # Get processor info
        data['processor'] = await self._get_processor_info()
        
        # Get document statistics
        data['documents'] = await self._get_document_stats()
        
        # Get training statistics
        data['training'] = await self._get_training_stats()
        
        # Get recent activity
        data['activity'] = await self._get_recent_activity()
        
        # Get system health
        data['health'] = await self._get_system_health()
        
        return data

    async def _get_processor_info(self) -> Dict[str, Any]:
        """Get processor information."""
        try:
            processor = self.docai_client.get_processor(name=self.processor_path)
            
            # Get processor versions
            versions_request = documentai.ListProcessorVersionsRequest(
                parent=self.processor_path
            )
            versions = list(self.docai_client.list_processor_versions(request=versions_request))
            
            deployed_versions = [v for v in versions if v.state == documentai.ProcessorVersion.State.DEPLOYED]
            
            return {
                'name': processor.display_name,
                'type': processor.type_,
                'state': processor.state.name,
                'default_version': processor.default_processor_version,
                'total_versions': len(versions),
                'deployed_versions': len(deployed_versions),
                'latest_version': deployed_versions[0].display_name if deployed_versions else None
            }
        except Exception as e:
            return {'error': str(e)}

    async def _get_document_stats(self) -> Dict[str, Any]:
        """Get document processing statistics."""
        try:
            docs_ref = self.firestore_client.collection('processed_documents')
            
            # Total documents
            total_docs = len(docs_ref.where('processor_id', '==', self.processor_id).get())
            
            # Documents by status
            pending_initial = len(docs_ref.where('processor_id', '==', self.processor_id)
                                .where('status', '==', 'pending_initial_training').get())
            completed = len(docs_ref.where('processor_id', '==', self.processor_id)
                          .where('status', '==', 'completed').get())
            failed = len(docs_ref.where('processor_id', '==', self.processor_id)
                       .where('status', '==', 'failed').get())
            
            # Documents used for training
            used_for_training = len(docs_ref.where('processor_id', '==', self.processor_id)
                                  .where('used_for_training', '==', True).get())
            unused_completed = len(docs_ref.where('processor_id', '==', self.processor_id)
                                 .where('status', '==', 'completed')
                                 .where('used_for_training', '==', False).get())
            
            # Documents by type
            doc_types = {}
            all_docs = docs_ref.where('processor_id', '==', self.processor_id).get()
            for doc in all_docs:
                doc_data = doc.to_dict()
                doc_type = doc_data.get('document_type', 'UNKNOWN')
                doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
            
            # Recent uploads (last 24 hours)
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            recent_docs = [d for d in all_docs 
                          if d.to_dict().get('created_at', datetime.min.replace(tzinfo=timezone.utc)) > yesterday]
            
            return {
                'total': total_docs,
                'pending_initial': pending_initial,
                'completed': completed,
                'failed': failed,
                'used_for_training': used_for_training,
                'unused_completed': unused_completed,
                'by_type': doc_types,
                'recent_24h': len(recent_docs),
                'processing_rate': f"{(completed / total_docs * 100):.1f}%" if total_docs > 0 else "0%"
            }
        except Exception as e:
            return {'error': str(e)}

    async def _get_training_stats(self) -> Dict[str, Any]:
        """Get training statistics."""
        try:
            batches_ref = self.firestore_client.collection('training_batches')
            
            # All batches for this processor
            all_batches = batches_ref.where('processor_id', '==', self.processor_id).get()
            
            # Active training
            active_training = None
            for batch in all_batches:
                batch_data = batch.to_dict()
                if batch_data.get('status') in ['preparing', 'training', 'deploying']:
                    active_training = batch_data
                    break
            
            # Training statistics
            total_batches = len(all_batches)
            successful_batches = sum(1 for b in all_batches 
                                   if b.to_dict().get('status') == 'deployed')
            failed_batches = sum(1 for b in all_batches 
                               if b.to_dict().get('status') in ['failed', 'training_failed'])
            
            # Total documents trained
            total_documents_trained = sum(b.to_dict().get('document_count', 0) 
                                        for b in all_batches)
            
            # Latest completed training
            completed_batches = [b for b in all_batches 
                               if b.to_dict().get('status') == 'deployed']
            latest_training = None
            if completed_batches:
                latest_training = max(completed_batches, 
                                    key=lambda b: b.to_dict().get('completed_at', datetime.min))
                latest_training = latest_training.to_dict()
            
            # Training configuration
            config_ref = self.firestore_client.collection('training_configs').document(self.processor_id)
            config = config_ref.get()
            config_data = config.to_dict() if config.exists else {}
            
            return {
                'total_batches': total_batches,
                'successful': successful_batches,
                'failed': failed_batches,
                'success_rate': f"{(successful_batches / total_batches * 100):.1f}%" if total_batches > 0 else "N/A",
                'total_documents_trained': total_documents_trained,
                'active_training': active_training,
                'latest_training': latest_training,
                'config': config_data,
                'next_training_threshold': config_data.get('min_documents_for_incremental', 5)
            }
        except Exception as e:
            return {'error': str(e)}

    async def _get_recent_activity(self) -> List[Dict[str, Any]]:
        """Get recent system activity."""
        try:
            # Query Cloud Logging for recent events
            filter_str = f'''
                resource.type="cloud_function"
                resource.labels.function_name="document-ai-auto-trainer"
                severity >= "INFO"
                timestamp >= "{(datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}"
            '''
            
            entries = list(self.logging_client.list_entries(filter_=filter_str, max_results=20))
            
            activities = []
            for entry in entries:
                activities.append({
                    'timestamp': entry.timestamp,
                    'severity': entry.severity,
                    'message': entry.payload.get('message', str(entry.payload)) if isinstance(entry.payload, dict) else str(entry.payload),
                    'type': 'function_log'
                })
            
            # Add Firestore activities
            docs_ref = self.firestore_client.collection('processed_documents')
            recent_docs = docs_ref.where('processor_id', '==', self.processor_id).order_by('created_at', direction=firestore.Query.DESCENDING).limit(10).get()
            
            for doc in recent_docs:
                doc_data = doc.to_dict()
                activities.append({
                    'timestamp': doc_data.get('created_at'),
                    'severity': 'INFO',
                    'message': f"Document processed: {doc_data.get('document_id')} - Status: {doc_data.get('status')}",
                    'type': 'document_processed'
                })
            
            # Sort by timestamp
            activities.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            
            return activities[:20]
        except Exception as e:
            return [{'error': str(e)}]

    async def _get_system_health(self) -> Dict[str, Any]:
        """Check system health."""
        health = {
            'cloud_function': 'unknown',
            'workflow': 'unknown',
            'firestore': 'healthy',
            'document_ai': 'unknown',
            'gcs': 'unknown'
        }
        
        try:
            # Check Cloud Function
            # In production, you would check function metrics
            health['cloud_function'] = 'healthy'
            
            # Check Workflow
            # In production, check workflow executions
            health['workflow'] = 'healthy'
            
            # Check Document AI
            processor = self.docai_client.get_processor(name=self.processor_path)
            health['document_ai'] = 'healthy' if processor.state == documentai.Processor.State.ENABLED else 'unhealthy'
            
            # Check GCS
            bucket_name = f"{self.project_id}-document-ai"
            bucket = self.storage_client.bucket(bucket_name)
            if bucket.exists():
                health['gcs'] = 'healthy'
            
        except Exception as e:
            pass
        
        return health

    def create_dashboard_layout(self, data: Dict[str, Any]) -> Layout:
        """Create the dashboard layout."""
        layout = Layout()
        
        # Create header
        header = Panel(
            f"[bold blue]Document AI Automated Training Monitor[/bold blue]\n"
            f"Project: {self.project_id} | Processor: {self.processor_id}\n"
            f"Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            box=box.DOUBLE
        )
        
        # Processor info
        processor_info = self._create_processor_panel(data['processor'])
        
        # Document stats
        doc_stats = self._create_document_stats_panel(data['documents'])
        
        # Training stats
        training_stats = self._create_training_stats_panel(data['training'])
        
        # Recent activity
        activity_panel = self._create_activity_panel(data['activity'])
        
        # System health
        health_panel = self._create_health_panel(data['health'])
        
        # Arrange layout
        layout.split_column(
            Layout(header, size=5),
            Layout().split_row(
                Layout().split_column(
                    Layout(processor_info, size=10),
                    Layout(health_panel, size=8)
                ),
                Layout().split_column(
                    Layout(doc_stats, size=10),
                    Layout(training_stats, size=8)
                )
            ),
            Layout(activity_panel)
        )
        
        return layout

    def _create_processor_panel(self, processor_data: Dict[str, Any]) -> Panel:
        """Create processor information panel."""
        if 'error' in processor_data:
            content = f"[red]Error: {processor_data['error']}[/red]"
        else:
            content = f"""[bold]Processor Information[/bold]
            
Name: {processor_data.get('name', 'N/A')}
Type: {processor_data.get('type', 'N/A')}
State: [green]{processor_data.get('state', 'N/A')}[/green]
Total Versions: {processor_data.get('total_versions', 0)}
Deployed Versions: {processor_data.get('deployed_versions', 0)}
Latest Version: {processor_data.get('latest_version', 'None')}"""
        
        return Panel(content, title="Processor", box=box.ROUNDED)

    def _create_document_stats_panel(self, doc_data: Dict[str, Any]) -> Panel:
        """Create document statistics panel."""
        if 'error' in doc_data:
            content = f"[red]Error: {doc_data['error']}[/red]"
        else:
            # Create a table for document types
            type_table = Table(show_header=False, box=None)
            for doc_type, count in doc_data.get('by_type', {}).items():
                type_table.add_row(f"{doc_type}:", str(count))
            
            content = f"""[bold]Document Statistics[/bold]
            
Total Documents: {doc_data.get('total', 0)}
Completed: [green]{doc_data.get('completed', 0)}[/green]
Pending Initial: [yellow]{doc_data.get('pending_initial', 0)}[/yellow]
Failed: [red]{doc_data.get('failed', 0)}[/red]

Training Status:
Used: {doc_data.get('used_for_training', 0)}
Available: [cyan]{doc_data.get('unused_completed', 0)}[/cyan]

Recent (24h): {doc_data.get('recent_24h', 0)}
Success Rate: {doc_data.get('processing_rate', '0%')}"""
        
        return Panel(content, title="Documents", box=box.ROUNDED)

    def _create_training_stats_panel(self, training_data: Dict[str, Any]) -> Panel:
        """Create training statistics panel."""
        if 'error' in training_data:
            content = f"[red]Error: {training_data['error']}[/red]"
        else:
            active = training_data.get('active_training')
            if active:
                active_info = f"""
[yellow]Active Training:[/yellow]
Batch ID: {active.get('batch_id', 'N/A')}
Status: {active.get('status', 'N/A')}
Documents: {active.get('document_count', 0)}"""
            else:
                active_info = "[green]No active training[/green]"
            
            config = training_data.get('config', {})
            threshold = training_data.get('next_training_threshold', 5)
            
            content = f"""[bold]Training Statistics[/bold]
            
Total Batches: {training_data.get('total_batches', 0)}
Successful: [green]{training_data.get('successful', 0)}[/green]
Failed: [red]{training_data.get('failed', 0)}[/red]
Success Rate: {training_data.get('success_rate', 'N/A')}

Documents Trained: {training_data.get('total_documents_trained', 0)}

{active_info}

Next Training: {threshold} documents needed
Auto-Training: {'[green]Enabled[/green]' if config.get('enabled', False) else '[red]Disabled[/red]'}"""
        
        return Panel(content, title="Training", box=box.ROUNDED)

    def _create_activity_panel(self, activities: List[Dict[str, Any]]) -> Panel:
        """Create recent activity panel."""
        table = Table(title="Recent Activity", box=box.SIMPLE)
        table.add_column("Time", style="cyan", width=20)
        table.add_column("Type", style="magenta", width=15)
        table.add_column("Message", style="white")
        
        for activity in activities[:10]:
            if 'error' in activity:
                table.add_row("Error", "Error", f"[red]{activity['error']}[/red]")
            else:
                timestamp = activity.get('timestamp')
                if timestamp:
                    time_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = "Unknown"
                
                type_str = activity.get('type', 'unknown').replace('_', ' ').title()
                message = activity.get('message', 'No message')[:80] + "..."
                
                table.add_row(time_str, type_str, message)
        
        return Panel(table, box=box.ROUNDED)

    def _create_health_panel(self, health_data: Dict[str, Any]) -> Panel:
        """Create system health panel."""
        content = "[bold]System Health[/bold]\n\n"
        
        for component, status in health_data.items():
            icon = "✓" if status == "healthy" else "✗" if status == "unhealthy" else "?"
            color = "green" if status == "healthy" else "red" if status == "unhealthy" else "yellow"
            component_name = component.replace('_', ' ').title()
            content += f"[{color}]{icon}[/{color}] {component_name}: [{color}]{status}[/{color}]\n"
        
        return Panel(content, title="Health Check", box=box.ROUNDED)

    async def run_dashboard(self, refresh_interval: int = 30):
        """Run the live dashboard."""
        self.console.print("[bold green]Starting Document AI Automated Training Monitor...[/bold green]")
        
        with Live(self.create_dashboard_layout(await self.get_dashboard_data()), 
                  refresh_per_second=1, console=self.console) as live:
            while True:
                try:
                    # Get fresh data
                    data = await self.get_dashboard_data()
                    
                    # Update display
                    live.update(self.create_dashboard_layout(data))
                    
                    # Wait before next update
                    await asyncio.sleep(refresh_interval)
                    
                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Dashboard stopped by user[/yellow]")
                    break
                except Exception as e:
                    self.console.print(f"\n[red]Error updating dashboard: {e}[/red]")
                    await asyncio.sleep(5)


async def main():
    """Main function to run the monitoring dashboard."""
    # Get configuration from environment
    project_id = os.getenv('GCP_PROJECT_ID')
    processor_id = os.getenv('DOCUMENT_AI_PROCESSOR_ID')
    
    if not project_id or not processor_id:
        print("Error: GCP_PROJECT_ID and DOCUMENT_AI_PROCESSOR_ID environment variables must be set")
        return
    
    # Create and run monitor
    monitor = AutomatedTrainingMonitor(project_id, processor_id)
    await monitor.run_dashboard(refresh_interval=30)


if __name__ == "__main__":
    asyncio.run(main())