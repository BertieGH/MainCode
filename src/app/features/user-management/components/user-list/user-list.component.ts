import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatTooltipModule } from '@angular/material/tooltip';
import { UserService } from '../../services/user.service';
import { User, UserRole } from '../../../../core/models/user.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatPaginatorModule,
    MatTooltipModule
  ],
  templateUrl: './user-list.component.html',
  styleUrls: ['./user-list.component.scss']
})
export class UserListComponent implements OnInit {
  users: User[] = [];
  loading = false;
  error: string | null = null;

  searchQuery = '';
  selectedRole = '';
  roles = Object.values(UserRole);

  totalCount = 0;
  pageNumber = 1;
  pageSize = 20;

  constructor(private userService: UserService, private pageTitle: PageTitleService) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('User Management', 'Manage system users');
    this.loadUsers();
  }

  loadUsers(): void {
    this.loading = true;
    this.error = null;

    this.userService.getUsers(
      this.pageNumber,
      this.pageSize,
      this.searchQuery || undefined,
      this.selectedRole || undefined
    ).subscribe({
      next: (result) => {
        this.users = result.items;
        this.totalCount = result.totalCount;
        this.loading = false;
      },
      error: (err) => {
        this.error = err.error?.message || 'Failed to load users';
        this.loading = false;
      }
    });
  }

  onSearch(): void {
    this.pageNumber = 1;
    this.loadUsers();
  }

  onRoleChange(): void {
    this.pageNumber = 1;
    this.loadUsers();
  }

  onPageChange(event: PageEvent): void {
    this.pageNumber = event.pageIndex + 1;
    this.pageSize = event.pageSize;
    this.loadUsers();
  }

  toggleActive(user: User): void {
    this.userService.toggleActive(user.id).subscribe({
      next: (updated) => {
        user.isActive = updated.isActive;
      },
      error: (err) => {
        alert('Error toggling user status: ' + (err.error?.message || err.message));
      }
    });
  }

  deleteUser(user: User): void {
    if (confirm(`Are you sure you want to delete user "${user.username}"?`)) {
      this.userService.deleteUser(user.id).subscribe({
        next: () => this.loadUsers(),
        error: (err) => {
          alert('Error deleting user: ' + (err.error?.message || err.message));
        }
      });
    }
  }
}
