using Survey.Core.DTOs.Common;
using Survey.Core.DTOs.User;

namespace Survey.Application.Services;

public interface IUserService
{
    Task<PagedResult<UserDto>> GetAllUsersAsync(int pageNumber, int pageSize);
    Task<UserDto?> GetUserByIdAsync(int id);
    Task<UserDto> CreateUserAsync(CreateUserDto dto);
    Task<UserDto> UpdateUserAsync(int id, UpdateUserDto dto);
    Task DeleteUserAsync(int id);
    Task<UserDto> ToggleActiveAsync(int id);
    Task<UserDto> ChangeRoleAsync(int id, string role);
    Task ChangePasswordAsync(int id, ChangePasswordDto dto);
}
