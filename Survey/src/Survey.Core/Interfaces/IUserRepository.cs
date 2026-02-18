using Survey.Core.Entities;

namespace Survey.Core.Interfaces;

public interface IUserRepository : IRepository<User>
{
    Task<User?> GetByUsernameAsync(string username);
    Task<User?> GetByEmailAsync(string email);
    Task<IEnumerable<User>> GetUsersPagedAsync(int pageNumber, int pageSize);
    Task<int> GetTotalUsersCountAsync();
}
