import { Routes } from '@angular/router';
import { MappingListComponent } from './components/mapping-list/mapping-list.component';
import { MappingTestComponent } from './components/mapping-test/mapping-test.component';

export const fieldMappingRoutes: Routes = [
  {
    path: '',
    component: MappingListComponent,
    title: 'Field Mappings'
  },
  {
    path: 'test',
    component: MappingTestComponent,
    title: 'Test Field Mappings'
  }
];
